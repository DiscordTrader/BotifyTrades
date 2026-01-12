"""
SQLite Database Management
Handles channels, trades, performance tracking, and encrypted config
"""
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
import threading
import functools
import time

# Cache for channel lookups (improves UI performance)
_channel_cache = {}
_channel_cache_timestamp = 0
_CHANNEL_CACHE_TTL = 60  # 60 seconds cache


def get_channel_map(force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
    """
    Get a cached mapping of discord_channel_id -> channel info.
    Used for efficient channel name lookups in trade displays.
    
    Returns:
        Dict mapping discord_channel_id (string) to:
        {
            'name': channel name,
            'category': channel category,
            'execute_enabled': bool,
            'track_enabled': bool,
            'broker_override': broker name or None
        }
    """
    global _channel_cache, _channel_cache_timestamp
    
    current_time = time.time()
    
    # Return cached data if still valid
    if not force_refresh and _channel_cache and (current_time - _channel_cache_timestamp) < _CHANNEL_CACHE_TTL:
        return _channel_cache
    
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT discord_channel_id, name, category, execute_enabled, track_enabled, broker_override
            FROM channels
            WHERE is_active = 1
        ''')
        rows = cursor.fetchall()
        
        _channel_cache = {}
        for row in rows:
            discord_id = str(row[0]) if row[0] else None
            if discord_id:
                _channel_cache[discord_id] = {
                    'name': row[1] or 'Unknown',
                    'category': row[2] or '',
                    'execute_enabled': bool(row[3]),
                    'track_enabled': bool(row[4]),
                    'broker_override': row[5]
                }
        
        _channel_cache_timestamp = current_time
        return _channel_cache
        
    except Exception as e:
        print(f"[DB] Error building channel map: {e}")
        return _channel_cache if _channel_cache else {}


def get_trade_source_display(trade: Dict) -> Dict[str, Any]:
    """
    Get display information for a trade's source channel.
    
    Priority: Channel lookup > Source-based fallback
    If channel_id exists and maps to a known channel, show that channel.
    Otherwise, fall back to source-based display (GUI, Sync, etc.)
    
    Args:
        trade: Trade dict with 'channel_id' and 'source' fields
        
    Returns:
        Dict with:
        {
            'name': Display name (e.g., "#jc-vip-alerts"),
            'type': 'execute', 'track', 'manual', 'sync', or 'unknown',
            'color': CSS color class for badge,
            'icon': Icon/emoji for display,
            'full_name': Full name with server context
        }
    """
    source = trade.get('source', 'discord')
    channel_id = trade.get('channel_id')
    
    # PRIORITY 1: If we have a channel_id, try to look it up first
    # This allows synced trades to still show their original channel
    if channel_id:
        channel_map = get_channel_map()
        channel_info = channel_map.get(str(channel_id))
        
        # Fallback: If not found by discord_channel_id, try internal database ID lookup
        if not channel_info:
            try:
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT discord_channel_id, name, category, execute_enabled, track_enabled
                    FROM channels WHERE id = ?
                ''', (channel_id,))
                row = cursor.fetchone()
                if row:
                    channel_info = {
                        'name': row[1] or 'Unknown',
                        'category': row[2] or '',
                        'execute_enabled': bool(row[3]),
                        'track_enabled': bool(row[4])
                    }
            except Exception:
                pass
        
        if channel_info:
            # Found the channel - display it with proper color coding
            if channel_info.get('execute_enabled'):
                channel_type = 'execute'
                color = 'blue'
                icon = '🎯'
            elif channel_info.get('track_enabled'):
                channel_type = 'track'
                color = 'purple'
                icon = '👁️'
            else:
                channel_type = 'inactive'
                color = 'gray'
                icon = '#'
            
            name = channel_info.get('name', 'Unknown')
            
            return {
                'name': f'#{name}',
                'type': channel_type,
                'color': color,
                'icon': icon,
                'full_name': f"#{name} ({channel_info.get('category', 'Discord')})"
            }
    
    # PRIORITY 2: Fall back to source-based display
    if source == 'gui' or source == 'manual':
        return {
            'name': 'Manual (GUI)',
            'type': 'manual',
            'color': 'gray',
            'icon': '🖥️',
            'full_name': 'Manual execution via web interface'
        }
    
    if source == 'sync' or source == 'broker_sync':
        return {
            'name': 'Broker Sync',
            'type': 'sync', 
            'color': 'gray',
            'icon': '🔄',
            'full_name': 'Synchronized from broker'
        }
    
    if source == 'risk_exit':
        return {
            'name': 'Risk Exit',
            'type': 'risk',
            'color': 'orange',
            'icon': '⚠️',
            'full_name': 'Automated risk management exit'
        }
    
    # PRIORITY 3: No channel_id and no recognized source
    if not channel_id:
        return {
            'name': 'Pre-tracking',
            'type': 'unknown',
            'color': 'dark',
            'icon': '📡',
            'full_name': 'Trade from before channel tracking was enabled'
        }
    
    # Channel ID exists but wasn't found in channel map
    return {
        'name': 'Unknown Channel',
        'type': 'unknown',
        'color': 'dark',
        'icon': '#',
        'full_name': f'Channel ID: {channel_id}'
    }


def calculate_trader_quality_score(user_stats: dict, max_total_pnl: float, min_total_pnl: float = 0) -> float:
    """
    Calculate Trader Quality Score (TQS) for ranking users/channels.
    
    Formula: TQS = (0.40 × Normalized PNL) + (0.25 × Profit Factor) + (0.20 × Win Rate) + (0.15 × Avg %PNL)
    
    Args:
        user_stats: Dict with keys: total_pnl, gross_profit, gross_loss, win_trades, loss_trades, avg_pct_pnl
        max_total_pnl: Maximum total PNL across all users (for normalization)
        min_total_pnl: Minimum total PNL across all users (for handling negative values)
    
    Returns:
        Float score between 0 and 1 (higher is better)
    """
    total_pnl = float(user_stats.get('total_pnl', 0) or 0)
    gross_profit = float(user_stats.get('gross_profit', 0) or 0)
    gross_loss = float(user_stats.get('gross_loss', 0) or 0)
    win_trades = int(user_stats.get('win_trades', 0) or 0)
    loss_trades = int(user_stats.get('loss_trades', 0) or 0)
    avg_pct = float(user_stats.get('avg_pct_pnl', 0) or 0)
    
    total_trades = win_trades + loss_trades
    
    # Normalized PNL (0-1 range, handles negative values)
    # Maps min_pnl->0, max_pnl->1
    pnl_range = max_total_pnl - min_total_pnl
    if pnl_range > 0:
        normalized_pnl = (total_pnl - min_total_pnl) / pnl_range
    elif max_total_pnl > 0:
        normalized_pnl = total_pnl / max_total_pnl
    else:
        normalized_pnl = 0.5  # Default if no variation
    normalized_pnl = max(0, min(1, normalized_pnl))  # Clamp to 0-1
    
    # Win rate (0-1 range)
    if total_trades > 0:
        win_rate = win_trades / total_trades
    else:
        win_rate = 0.0
    
    # Profit factor (capped at 2.0 for scoring, raw value stored separately)
    if gross_loss == 0:
        if gross_profit > 0:
            profit_factor_capped = 2.0
        else:
            profit_factor_capped = 0.0
    else:
        profit_factor_raw = gross_profit / abs(gross_loss)
        profit_factor_capped = min(profit_factor_raw, 2.0)
    
    # Normalize profit factor to 0-1 range (divide by cap of 2.0)
    profit_factor_normalized = profit_factor_capped / 2.0
    
    # Normalize avg %PNL (assume reasonable range is -100% to +200%, scale to 0-1)
    avg_pct_normalized = max(0, min(1, (avg_pct + 100) / 300))
    
    # Final Trader Quality Score (scaled to 0-100 for display)
    score = (
        (0.40 * normalized_pnl) +
        (0.25 * profit_factor_normalized) +
        (0.20 * win_rate) +
        (0.15 * avg_pct_normalized)
    ) * 100  # Scale to 0-100 for better display
    
    return round(score, 1)


def get_date_filter_bounds(period: str, start_date: str = None, end_date: str = None) -> Tuple[str, str]:
    """
    Get start and end date strings for filtering by close_date.
    
    Args:
        period: 'today', '7d', '30d', 'year', 'all', or 'custom'
        start_date: ISO date string for custom range (YYYY-MM-DD)
        end_date: ISO date string for custom range (YYYY-MM-DD)
    
    Returns:
        Tuple of (start_date_str, end_date_str) for SQL filtering
    """
    now = datetime.now()
    end = now.strftime('%Y-%m-%d 23:59:59')
    
    if period == 'today':
        start = now.strftime('%Y-%m-%d 00:00:00')
    elif period == '7d' or period == 'week':
        start = (now - timedelta(days=7)).strftime('%Y-%m-%d 00:00:00')
    elif period == '30d' or period == 'month':
        start = (now - timedelta(days=30)).strftime('%Y-%m-%d 00:00:00')
    elif period == 'year':
        start = (now - timedelta(days=365)).strftime('%Y-%m-%d 00:00:00')
    elif period == 'custom' and start_date and end_date:
        start = f"{start_date} 00:00:00"
        end = f"{end_date} 23:59:59"
    else:
        start = None
        end = None
    
    return (start, end)

# Thread-local storage for database connections
_local = threading.local()

def get_db_path():
    """Get database file path - handles both development and PyInstaller modes"""
    import sys
    
    # Check if running as PyInstaller bundle
    if getattr(sys, 'frozen', False):
        # Running as compiled executable - use executable's directory
        base_path = Path(sys.executable).parent
    else:
        # Running as script - use current working directory
        base_path = Path.cwd()
    
    db_path = base_path / 'bot_data.db'
    
    # Ensure parent directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    return db_path


def get_connection():
    """Get thread-safe database connection"""
    if not hasattr(_local, 'connection'):
        _local.connection = sqlite3.connect(
            get_db_path(),
            check_same_thread=False
        )
        _local.connection.row_factory = sqlite3.Row
    return _local.connection


def init_db():
    """Initialize database schema"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Channels table (execution vs tracking)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_channel_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL CHECK(category IN ('EXECUTE', 'TRACK')),
            execute_enabled INTEGER DEFAULT 0,
            track_enabled INTEGER DEFAULT 0,
            broker_override TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Migrate existing data: Add columns if they don't exist
    try:
        cursor.execute('SELECT execute_enabled FROM channels LIMIT 1')
    except sqlite3.OperationalError:
        # Columns don't exist, add them
        cursor.execute('ALTER TABLE channels ADD COLUMN execute_enabled INTEGER DEFAULT 0')
        cursor.execute('ALTER TABLE channels ADD COLUMN track_enabled INTEGER DEFAULT 0')
        
        # Backfill based on category
        cursor.execute("UPDATE channels SET execute_enabled = 1 WHERE category = 'EXECUTE'")
        cursor.execute("UPDATE channels SET track_enabled = 1 WHERE category = 'TRACK'")
        conn.commit()
        print("[DATABASE] ✓ Migrated to dual-mode channel flags")
    
    # Migrate: Add paper trading columns if they don't exist
    try:
        cursor.execute('SELECT paper_trade_enabled FROM channels LIMIT 1')
    except sqlite3.OperationalError:
        # Paper trading columns don't exist, add them
        cursor.execute('ALTER TABLE channels ADD COLUMN paper_trade_enabled INTEGER DEFAULT 0')
        cursor.execute('ALTER TABLE channels ADD COLUMN profit_target_pct REAL DEFAULT NULL')
        cursor.execute('ALTER TABLE channels ADD COLUMN profit_target_1_pct REAL DEFAULT NULL')
        cursor.execute('ALTER TABLE channels ADD COLUMN profit_target_2_pct REAL DEFAULT NULL')
        cursor.execute('ALTER TABLE channels ADD COLUMN profit_target_3_pct REAL DEFAULT NULL')
        cursor.execute('ALTER TABLE channels ADD COLUMN stop_loss_pct REAL DEFAULT NULL')
        cursor.execute('ALTER TABLE channels ADD COLUMN trailing_stop_pct REAL DEFAULT NULL')
        cursor.execute('ALTER TABLE channels ADD COLUMN trailing_activation_pct REAL DEFAULT NULL')
        conn.commit()
        print("[DATABASE] ✓ Added paper trading and risk management columns")
    
    # Migrate: Add enabled_brokers column for multi-broker execution
    try:
        cursor.execute('SELECT enabled_brokers FROM channels LIMIT 1')
    except sqlite3.OperationalError:
        # Column doesn't exist, add it
        cursor.execute('ALTER TABLE channels ADD COLUMN enabled_brokers TEXT DEFAULT NULL')
        conn.commit()
        print("[DATABASE] ✓ Added enabled_brokers column for multi-broker execution")
    
    # Migrate: Add profit target columns if they don't exist
    try:
        cursor.execute('SELECT profit_target_1_pct FROM channels LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute('ALTER TABLE channels ADD COLUMN profit_target_1_pct REAL DEFAULT NULL')
        cursor.execute('ALTER TABLE channels ADD COLUMN profit_target_2_pct REAL DEFAULT NULL')
        cursor.execute('ALTER TABLE channels ADD COLUMN profit_target_3_pct REAL DEFAULT NULL')
        conn.commit()
        print("[DATABASE] ✓ Added 3-tier profit target columns")
    
    # Migrate: Add position_size_pct column for per-channel percentage-based position sizing (execution)
    try:
        cursor.execute('SELECT position_size_pct FROM channels LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute('ALTER TABLE channels ADD COLUMN position_size_pct REAL DEFAULT NULL')
        conn.commit()
        print("[DATABASE] ✓ Added position_size_pct column for percentage-based position sizing")
    
    # Migrate: Add tracking_position_size_pct column for paper trading position sizing
    try:
        cursor.execute('SELECT tracking_position_size_pct FROM channels LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute('ALTER TABLE channels ADD COLUMN tracking_position_size_pct REAL DEFAULT NULL')
        conn.commit()
        print("[DATABASE] ✓ Added tracking_position_size_pct column for paper trading position sizing")
    
    # Migrate: Add risk_management_enabled column for per-channel risk opt-in
    try:
        cursor.execute('SELECT risk_management_enabled FROM channels LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute('ALTER TABLE channels ADD COLUMN risk_management_enabled INTEGER DEFAULT 0')
        conn.commit()
        print("[DATABASE] ✓ Added risk_management_enabled column for per-channel risk opt-in")
    
    # Migrate: Add default_quantity column for per-channel fixed quantity default
    try:
        cursor.execute('SELECT default_quantity FROM channels LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute('ALTER TABLE channels ADD COLUMN default_quantity INTEGER DEFAULT NULL')
        conn.commit()
        print("[DATABASE] ✓ Added default_quantity column for per-channel fixed quantity default")
    
    # Migrate: Add leave_runner columns for per-channel runner settings
    try:
        cursor.execute('SELECT leave_runner_enabled FROM channels LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute('ALTER TABLE channels ADD COLUMN leave_runner_enabled INTEGER DEFAULT 0')
        cursor.execute('ALTER TABLE channels ADD COLUMN leave_runner_pct REAL DEFAULT 25.0')
        conn.commit()
        print("[DATABASE] ✓ Added leave_runner columns for per-channel runner settings")
    
    # Migrate: Add P4 profit target and per-tier quantity columns for enhanced risk management
    try:
        cursor.execute('SELECT profit_target_4_pct FROM channels LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute('ALTER TABLE channels ADD COLUMN profit_target_4_pct REAL DEFAULT NULL')
        cursor.execute('ALTER TABLE channels ADD COLUMN profit_target_qty_1 INTEGER DEFAULT NULL')
        cursor.execute('ALTER TABLE channels ADD COLUMN profit_target_qty_2 INTEGER DEFAULT NULL')
        cursor.execute('ALTER TABLE channels ADD COLUMN profit_target_qty_3 INTEGER DEFAULT NULL')
        cursor.execute('ALTER TABLE channels ADD COLUMN profit_target_qty_4 INTEGER DEFAULT NULL')
        conn.commit()
        print("[DATABASE] ✓ Added P4 and per-tier quantity columns for enhanced risk management")
    
    # Migrate: Add trim order mode columns for limit vs market order trims
    try:
        cursor.execute('SELECT trim_order_mode FROM channels LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE channels ADD COLUMN trim_order_mode TEXT DEFAULT 'market'")
        cursor.execute('ALTER TABLE channels ADD COLUMN trim_limit_offset REAL DEFAULT 0.01')
        conn.commit()
        print("[DATABASE] ✓ Added trim order mode columns (market/limit) for per-channel trim settings")
    
    # Migrate: Add exit strategy mode column for choosing between signal-based vs risk-based exits
    # Options: 'signal' (follow trader's trims/stops), 'risk' (use risk management auto-exits), 'hybrid' (both)
    try:
        cursor.execute('SELECT exit_strategy_mode FROM channels LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE channels ADD COLUMN exit_strategy_mode TEXT DEFAULT 'signal'")
        conn.commit()
        print("[DATABASE] ✓ Added exit_strategy_mode column for per-channel exit strategy")
    
    # Migrate: Add platform support for multi-platform channels (Discord + Telegram)
    try:
        cursor.execute('SELECT platform FROM channels LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE channels ADD COLUMN platform TEXT DEFAULT 'discord'")
        cursor.execute('ALTER TABLE channels ADD COLUMN telegram_chat_id TEXT DEFAULT NULL')
        cursor.execute('ALTER TABLE channels ADD COLUMN telegram_chat_type TEXT DEFAULT NULL')
        cursor.execute('ALTER TABLE channels ADD COLUMN telegram_username TEXT DEFAULT NULL')
        conn.commit()
        print("[DATABASE] ✓ Added platform columns for multi-platform support (Discord + Telegram)")
    
    # Migrate: Add market column for regional market segmentation (US, IN, CA)
    try:
        cursor.execute('SELECT market FROM channels LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE channels ADD COLUMN market TEXT DEFAULT 'US'")
        conn.commit()
        print("[DATABASE] ✓ Added market column for regional segmentation (US, IN, CA)")
    
    # Migrate: Add trade_summary_enabled column for per-channel P/L posting toggle
    try:
        cursor.execute('SELECT trade_summary_enabled FROM channels LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute('ALTER TABLE channels ADD COLUMN trade_summary_enabled INTEGER DEFAULT 1')
        conn.commit()
        print("[DATABASE] ✓ Added trade_summary_enabled column for per-channel P/L posting")
    
    # Migrate: Add per-channel slippage protection columns
    try:
        cursor.execute('SELECT slippage_protection_enabled FROM channels LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute('ALTER TABLE channels ADD COLUMN slippage_protection_enabled INTEGER DEFAULT 0')
        cursor.execute('ALTER TABLE channels ADD COLUMN slippage_max_pct REAL DEFAULT NULL')
        conn.commit()
        print("[DATABASE] ✓ Added per-channel slippage protection columns")
    
    # ============================================
    # OMS/RMS COLUMNS - Signal Update Automation & Risk Management
    # ============================================
    
    # Migrate: Add signal update automation columns for C1apped/WaxUI dynamic updates
    try:
        cursor.execute('SELECT signal_update_automation FROM channels LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute('ALTER TABLE channels ADD COLUMN signal_update_automation INTEGER DEFAULT 0')
        cursor.execute('ALTER TABLE channels ADD COLUMN signal_update_automation_override TEXT DEFAULT NULL')
        cursor.execute('ALTER TABLE channels ADD COLUMN exit_strategy_mode_override TEXT DEFAULT NULL')
        cursor.execute('ALTER TABLE channels ADD COLUMN use_global_risk_settings INTEGER DEFAULT 1')
        cursor.execute('ALTER TABLE channels ADD COLUMN channel_daily_loss_limit REAL DEFAULT 0')
        cursor.execute('ALTER TABLE channels ADD COLUMN channel_max_positions INTEGER DEFAULT 0')
        cursor.execute('ALTER TABLE channels ADD COLUMN circuit_breaker_enabled INTEGER DEFAULT 1')
        conn.commit()
        print("[DATABASE] ✓ Added OMS/RMS columns for signal update automation")
    
    # Conversion channels table (for automatic AI signal conversion)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conversion_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_channel_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            target_execution_channel_id TEXT,
            is_active INTEGER DEFAULT 1,
            learning_examples TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Settings table (global configuration)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY,
            key TEXT UNIQUE NOT NULL,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Telegram settings table for API credentials
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS telegram_settings (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            enabled INTEGER DEFAULT 0,
            api_id TEXT,
            api_hash TEXT,
            phone_number TEXT,
            session_string TEXT,
            session_status TEXT DEFAULT 'disconnected',
            last_connected_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Initialize Telegram settings row if not exists
    cursor.execute('''
        INSERT OR IGNORE INTO telegram_settings (id, enabled) VALUES (1, 0)
    ''')
    
    # Migrate: Add Alpaca settings columns if settings table exists but columns missing
    try:
        cursor.execute('SELECT value FROM settings WHERE key = "alpaca_api_key" LIMIT 1')
    except sqlite3.OperationalError:
        pass  # Table doesn't exist yet, will be created above
    
    conn.commit()
    
    # Trades table (all executed trades)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT,
            message_id TEXT,
            direction TEXT NOT NULL CHECK(direction IN ('BTO', 'STC')),
            asset_type TEXT NOT NULL CHECK(asset_type IN ('stock', 'option')),
            symbol TEXT NOT NULL,
            strike REAL,
            expiry TEXT,
            call_put TEXT,
            quantity INTEGER NOT NULL,
            intended_price REAL,
            executed_price REAL,
            current_price REAL,
            executed_at TIMESTAMP,
            closed_at TIMESTAMP,
            status TEXT DEFAULT 'OPEN' CHECK(status IN ('OPEN', 'CLOSED', 'PENDING', 'FAILED')),
            pnl REAL DEFAULT 0,
            pnl_percent REAL DEFAULT 0,
            broker TEXT,
            order_id TEXT,
            stop_loss_price REAL,
            profit_target_price REAL,
            FOREIGN KEY (channel_id) REFERENCES channels(id)
        )
    ''')
    
    # Migration: Add stop_loss_price and profit_target_price columns if they don't exist
    try:
        cursor.execute('SELECT stop_loss_price FROM trades LIMIT 1')
    except sqlite3.OperationalError:
        print("[DATABASE] Adding stop_loss_price and profit_target_price columns to trades table...")
        cursor.execute('ALTER TABLE trades ADD COLUMN stop_loss_price REAL')
        cursor.execute('ALTER TABLE trades ADD COLUMN profit_target_price REAL')
        conn.commit()
        print("[DATABASE] ✓ Per-signal stop/target price columns added")
    
    # Migration: Add risk_trigger column to track automated exit reasons
    try:
        cursor.execute('SELECT risk_trigger FROM trades LIMIT 1')
    except sqlite3.OperationalError:
        print("[DATABASE] Adding risk_trigger column to trades table...")
        cursor.execute('ALTER TABLE trades ADD COLUMN risk_trigger TEXT')
        conn.commit()
        print("[DATABASE] ✓ Risk trigger tracking column added")
    
    # Migration: Add origin_trade_id column to link STC to original BTO for risk-managed trades
    try:
        cursor.execute('SELECT origin_trade_id FROM trades LIMIT 1')
    except sqlite3.OperationalError:
        print("[DATABASE] Adding origin_trade_id column to trades table...")
        cursor.execute('ALTER TABLE trades ADD COLUMN origin_trade_id INTEGER')
        conn.commit()
        print("[DATABASE] ✓ Origin trade ID linking column added")
    
    # Migration: Add user_id column for user-based performance tracking
    try:
        cursor.execute('SELECT user_id FROM trades LIMIT 1')
    except sqlite3.OperationalError:
        print("[DATABASE] Adding user_id column to trades table...")
        cursor.execute('ALTER TABLE trades ADD COLUMN user_id INTEGER')
        conn.commit()
        print("[DATABASE] ✓ User ID tracking column added")
    
    # Migration: Add source column to track where trades originated (discord, gui, api)
    try:
        cursor.execute('SELECT source FROM trades LIMIT 1')
    except sqlite3.OperationalError:
        print("[DATABASE] Adding source column to trades table...")
        cursor.execute("ALTER TABLE trades ADD COLUMN source TEXT DEFAULT 'discord'")
        conn.commit()
        print("[DATABASE] ✓ Trade source tracking column added")
    
    # Migration: Add option_id column to store broker's option contract ID
    try:
        cursor.execute('SELECT option_id FROM trades LIMIT 1')
    except sqlite3.OperationalError:
        print("[DATABASE] Adding option_id column to trades table...")
        cursor.execute('ALTER TABLE trades ADD COLUMN option_id TEXT')
        conn.commit()
        print("[DATABASE] ✓ Option ID tracking column added")
    
    # Migration: Add close_reason column to track why a trade was closed
    try:
        cursor.execute('SELECT close_reason FROM trades LIMIT 1')
    except sqlite3.OperationalError:
        print("[DATABASE] Adding close_reason column to trades table...")
        cursor.execute("ALTER TABLE trades ADD COLUMN close_reason TEXT")
        conn.commit()
        print("[DATABASE] ✓ Close reason tracking column added")
    
    # Migration: Fix trades with UNKNOWN broker - default to Webull
    cursor.execute("UPDATE trades SET broker = 'Webull' WHERE broker = 'UNKNOWN' OR broker IS NULL OR broker = ''")
    if cursor.rowcount > 0:
        print(f"[DATABASE] ✓ Fixed {cursor.rowcount} trades with UNKNOWN/NULL broker → Webull")
        conn.commit()
    
    # Migration: Add market column for India/US market segmentation
    try:
        cursor.execute('SELECT market FROM trades LIMIT 1')
    except sqlite3.OperationalError:
        print("[DATABASE] Adding market column to trades table...")
        cursor.execute("ALTER TABLE trades ADD COLUMN market TEXT DEFAULT 'US'")
        conn.commit()
        print("[DATABASE] ✓ Market segmentation column added")
    
    # Migration: Add currency column for multi-currency support
    try:
        cursor.execute('SELECT currency FROM trades LIMIT 1')
    except sqlite3.OperationalError:
        print("[DATABASE] Adding currency column to trades table...")
        cursor.execute("ALTER TABLE trades ADD COLUMN currency TEXT DEFAULT 'USD'")
        conn.commit()
        print("[DATABASE] ✓ Currency tracking column added")
    
    # Migration: Add lot_size column for India F&O lot tracking
    try:
        cursor.execute('SELECT lot_size FROM trades LIMIT 1')
    except sqlite3.OperationalError:
        print("[DATABASE] Adding lot_size column to trades table...")
        cursor.execute("ALTER TABLE trades ADD COLUMN lot_size INTEGER DEFAULT 1")
        conn.commit()
        print("[DATABASE] ✓ Lot size tracking column added")
    
    # Migration: Add trailing stop state columns for persistence across restarts
    try:
        cursor.execute('SELECT trailing_activated FROM trades LIMIT 1')
    except sqlite3.OperationalError:
        print("[DATABASE] Adding trailing stop state columns to trades table...")
        cursor.execute("ALTER TABLE trades ADD COLUMN trailing_activated INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE trades ADD COLUMN highest_price REAL")
        cursor.execute("ALTER TABLE trades ADD COLUMN trailing_activated_at TIMESTAMP")
        conn.commit()
        print("[DATABASE] ✓ Trailing stop state columns added (trailing_activated, highest_price, trailing_activated_at)")
    
    # Signals table (all signals received, including tracked ones)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT,
            message_id TEXT UNIQUE,
            direction TEXT NOT NULL,
            asset_type TEXT NOT NULL,
            symbol TEXT NOT NULL,
            strike REAL,
            expiry TEXT,
            call_put TEXT,
            quantity INTEGER,
            price REAL,
            author_name TEXT,
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            executed INTEGER DEFAULT 0,
            FOREIGN KEY (channel_id) REFERENCES channels(id)
        )
    ''')
    
    # Migration: Add execution_status and execution_reason to signals table
    try:
        cursor.execute('SELECT execution_status FROM signals LIMIT 1')
    except sqlite3.OperationalError:
        print("[DATABASE] Adding execution_status and execution_reason columns to signals table...")
        cursor.execute("ALTER TABLE signals ADD COLUMN execution_status TEXT DEFAULT 'PENDING'")
        cursor.execute("ALTER TABLE signals ADD COLUMN execution_reason TEXT")
        conn.commit()
        print("[DATABASE] ✓ Signal execution status tracking columns added")
    
    # Migration: Add market column to signals table for India market segmentation
    try:
        cursor.execute('SELECT market FROM signals LIMIT 1')
    except sqlite3.OperationalError:
        print("[DATABASE] Adding market column to signals table...")
        cursor.execute("ALTER TABLE signals ADD COLUMN market TEXT DEFAULT 'US'")
        conn.commit()
        print("[DATABASE] ✓ Market segmentation column added to signals")
    
    # Migration: Add comprehensive signal tracking columns for full lifecycle visibility
    signal_tracking_columns = [
        ('source_platform', "TEXT DEFAULT 'discord'"),
        ('guild_id', 'TEXT'),
        ('author_id', 'TEXT'),
        ('broker_target', 'TEXT'),
        ('broker_order_id', 'TEXT'),
        ('broker_response', 'TEXT'),
        ('status_timestamps', 'TEXT'),
        ('last_error', 'TEXT'),
        ('pnl_realized', 'REAL'),
        ('pnl_percent', 'REAL'),
        ('detected_at', 'TIMESTAMP'),
        ('validated_at', 'TIMESTAMP'),
        ('submitted_at', 'TIMESTAMP'),
        ('executed_at', 'TIMESTAMP'),
        ('raw_message', 'TEXT'),
    ]
    for col_name, col_type in signal_tracking_columns:
        try:
            cursor.execute(f'SELECT {col_name} FROM signals LIMIT 1')
        except sqlite3.OperationalError:
            print(f"[DATABASE] Adding {col_name} column to signals table...")
            cursor.execute(f"ALTER TABLE signals ADD COLUMN {col_name} {col_type}")
            conn.commit()
    
    # Signal Event Transitions - Immutable audit trail for signal lifecycle
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signal_event_transitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER NOT NULL,
            from_status TEXT,
            to_status TEXT NOT NULL,
            details TEXT,
            actor TEXT DEFAULT 'system',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (signal_id) REFERENCES signals(id)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_transitions_signal ON signal_event_transitions(signal_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_transitions_status ON signal_event_transitions(to_status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_transitions_time ON signal_event_transitions(created_at)')
    
    # Additional indexes for signal history filtering
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_market ON signals(market)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(execution_status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_broker ON signals(broker_target)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_received ON signals(received_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_author ON signals(author_id)')
    
    # Signal lots (BTO positions tracking for FIFO matching)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signal_lots (
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
            FOREIGN KEY (channel_id) REFERENCES channels(id),
            FOREIGN KEY (signal_id) REFERENCES signals(id),
            FOREIGN KEY (trade_id) REFERENCES trades(id)
        )
    ''')
    
    # Lot closures (STC matching records with PNL)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lot_closures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lot_id INTEGER NOT NULL,
            channel_id TEXT NOT NULL,
            signal_id INTEGER,
            trade_id INTEGER,
            closed_qty INTEGER NOT NULL,
            close_price REAL NOT NULL,
            closed_at TIMESTAMP NOT NULL,
            pnl REAL NOT NULL,
            pnl_percent REAL NOT NULL,
            holding_days REAL,
            author_name TEXT,
            exit_reason TEXT,
            FOREIGN KEY (lot_id) REFERENCES signal_lots(id),
            FOREIGN KEY (channel_id) REFERENCES channels(id),
            FOREIGN KEY (signal_id) REFERENCES signals(id),
            FOREIGN KEY (trade_id) REFERENCES trades(id)
        )
    ''')
    
    # Performance snapshots (pre-calculated metrics)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS performance_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT,
            period_start TIMESTAMP,
            period_end TIMESTAMP,
            total_signals INTEGER DEFAULT 0,
            executed_signals INTEGER DEFAULT 0,
            win_count INTEGER DEFAULT 0,
            loss_count INTEGER DEFAULT 0,
            win_rate REAL DEFAULT 0,
            pnl_total REAL DEFAULT 0,
            pnl_avg REAL DEFAULT 0,
            signal_accuracy REAL DEFAULT 0,
            FOREIGN KEY (channel_id) REFERENCES channels(id)
        )
    ''')
    
    # Config storage (encrypted credentials)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value_encrypted BLOB,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Slippage protection settings
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS slippage_settings (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            enabled INTEGER DEFAULT 1,
            threshold_percent REAL DEFAULT 10.0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Insert default slippage settings if not exists
    cursor.execute('''
        INSERT OR IGNORE INTO slippage_settings (id, enabled, threshold_percent)
        VALUES (1, 1, 10.0)
    ''')
    
    # Global risk management settings
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS risk_management_settings (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            enabled INTEGER DEFAULT 0,
            profit_target_percent REAL DEFAULT 20.0,
            stop_loss_percent REAL DEFAULT 10.0,
            trailing_stop_percent REAL DEFAULT 5.0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        INSERT OR IGNORE INTO risk_management_settings 
        (id, enabled, profit_target_percent, stop_loss_percent, trailing_stop_percent)
        VALUES (1, 0, 20.0, 10.0, 5.0)
    ''')
    
    # AI analysis settings
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ai_settings (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            enabled INTEGER DEFAULT 1,
            model TEXT DEFAULT 'gpt-4o-mini',
            sentiment_enabled INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        INSERT OR IGNORE INTO ai_settings 
        (id, enabled, model, sentiment_enabled)
        VALUES (1, 1, 'gpt-4o-mini', 0)
    ''')
    
    # Trading settings
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trading_settings (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            max_position_size INTEGER DEFAULT 600,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        INSERT OR IGNORE INTO trading_settings 
        (id, max_position_size)
        VALUES (1, 600)
    ''')
    
    # Migrate: Add global_default_quantity column to trading_settings
    try:
        cursor.execute('SELECT global_default_quantity FROM trading_settings LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute('ALTER TABLE trading_settings ADD COLUMN global_default_quantity INTEGER DEFAULT NULL')
        conn.commit()
        print("[DATABASE] ✓ Added global_default_quantity column to trading_settings")
    
    # Migrate: Add max_position_size_enabled column to trading_settings
    try:
        cursor.execute('SELECT max_position_size_enabled FROM trading_settings LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute('ALTER TABLE trading_settings ADD COLUMN max_position_size_enabled INTEGER DEFAULT 1')
        conn.commit()
        print("[DATABASE] ✓ Added max_position_size_enabled column to trading_settings")
    
    # Migrate: Add trade_summary_enabled column to trading_settings (global toggle)
    try:
        cursor.execute('SELECT trade_summary_enabled FROM trading_settings LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute('ALTER TABLE trading_settings ADD COLUMN trade_summary_enabled INTEGER DEFAULT 1')
        conn.commit()
        print("[DATABASE] ✓ Added trade_summary_enabled column to trading_settings (global toggle)")
    
    # Discord settings (moved from config.ini to GUI)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS discord_settings (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            allow_self_messages INTEGER DEFAULT 0,
            discovery_mode INTEGER DEFAULT 0,
            option_pattern TEXT DEFAULT '^(BTO|STC)\\s+(?:(\\d+)\\s+)?\\$?([A-Za-z]+)\\s+\\$?([\\d.]+)\\s*([CPcp])\\s*(\\d{1,2}/\\d{1,2})\\s*@?\\s*([\\d.]+|[mM])',
            stock_pattern TEXT DEFAULT '^(BTO|STC)\\s+(?:(\\d+)\\s+)?\\$?([A-Za-z]+)\\s*@?\\s*([\\d.]+|[mM])',
            allowed_author_ids TEXT DEFAULT '',
            allowed_guild_ids TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        INSERT OR IGNORE INTO discord_settings 
        (id, allow_self_messages, discovery_mode, option_pattern, stock_pattern, allowed_author_ids, allowed_guild_ids)
        VALUES (1, 0, 0, '^(BTO|STC)\\s+(?:(\\d+)\\s+)?\\$?([A-Za-z]+)\\s+\\$?([\\d.]+)\\s*([CPcp])\\s*(\\d{1,2}/\\d{1,2})\\s*@?\\s*([\\d.]+|[mM])', '^(BTO|STC)\\s+(?:(\\d+)\\s+)?\\$?([A-Za-z]+)\\s*@?\\s*([\\d.]+|[mM])', '', '')
    ''')
    
    # Position risk management settings (profit targets, stop losses, trailing stops)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS position_risk_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER UNIQUE NOT NULL,
            profit_target_percent REAL DEFAULT 20.0,
            stop_loss_percent REAL DEFAULT 10.0,
            trailing_stop_enabled INTEGER DEFAULT 0,
            trailing_stop_percent REAL DEFAULT 5.0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (trade_id) REFERENCES trades(id) ON DELETE CASCADE
        )
    ''')
    
    # ============================================
    # GLOBAL OMS/RMS SETTINGS
    # ============================================
    
    # Global risk settings - Signal Update Automation, Circuit Breaker, etc.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS global_risk_settings (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            enable_signal_update_automation INTEGER DEFAULT 0,
            exit_strategy_mode TEXT DEFAULT 'signal',
            enable_circuit_breaker INTEGER DEFAULT 0,
            enable_trailing_execution INTEGER DEFAULT 0,
            global_daily_loss_limit REAL DEFAULT 0,
            global_max_positions INTEGER DEFAULT 10,
            order_timeout_minutes INTEGER DEFAULT 5,
            acknowledged_v2_features INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        INSERT OR IGNORE INTO global_risk_settings (id) VALUES (1)
    ''')
    
    # Risk events audit log - Immutable record of all risk decisions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS risk_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            signal_instance_id INTEGER,
            channel_id TEXT,
            source TEXT,
            details TEXT,
            before_state TEXT,
            after_state TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_risk_events_instance ON risk_events(signal_instance_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_risk_events_channel ON risk_events(channel_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_risk_events_type ON risk_events(event_type)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_risk_events_created ON risk_events(created_at)')
    
    # Application Users (login credentials for control panel)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS app_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
    ''')
    
    # Password reset tokens (for forgot password feature)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE CASCADE
        )
    ''')
    
    # Email configuration
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS email_config (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            email_provider TEXT DEFAULT 'gmail',
            smtp_host TEXT,
            smtp_port INTEGER,
            smtp_user TEXT,
            smtp_password_encrypted BLOB,
            sender_email TEXT,
            sender_name TEXT,
            enabled INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        INSERT OR IGNORE INTO email_config (id, email_provider)
        VALUES (1, 'gmail')
    ''')
    
    # Channel allowed users (per-channel user filtering for execution/tracking)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS channel_allowed_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL,
            discord_user_id TEXT NOT NULL,
            discord_username TEXT NOT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
            UNIQUE(channel_id, discord_user_id)
        )
    ''')
    
    # Waitlist for interested users (public signup)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS waitlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT,
            source TEXT DEFAULT 'docs_page',
            queue_position INTEGER,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'invited', 'registered', 'declined')),
            referral_code TEXT,
            referred_by INTEGER,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            invited_at TIMESTAMP,
            registered_at TIMESTAMP,
            FOREIGN KEY (referred_by) REFERENCES waitlist(id)
        )
    ''')
    
    # Error logs for AI assistant context awareness
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS error_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            error_type TEXT NOT NULL,
            error_code TEXT,
            error_message TEXT NOT NULL,
            component TEXT,
            context TEXT,
            stack_trace TEXT,
            severity TEXT DEFAULT 'error' CHECK(severity IN ('info', 'warning', 'error', 'critical')),
            occurrence_count INTEGER DEFAULT 1,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved INTEGER DEFAULT 0,
            resolution_notes TEXT,
            user_notified INTEGER DEFAULT 0
        )
    ''')
    
    # Known issues database with solutions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS known_issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            error_pattern TEXT NOT NULL,
            issue_title TEXT NOT NULL,
            issue_description TEXT,
            solution TEXT NOT NULL,
            category TEXT,
            keywords TEXT,
            auto_detect INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # ==================== CLIENT-SIDE LICENSE STORAGE ====================
    # Local storage for activated license (persists across restarts)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS local_license (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            license_key TEXT NOT NULL,
            machine_id TEXT NOT NULL,
            license_type TEXT DEFAULT 'subscription',
            days_remaining INTEGER DEFAULT 0,
            expires_at TIMESTAMP,
            signed_token TEXT,
            last_validated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # ==================== SERVER-SIDE LICENSE TABLES ====================
    # These tables are used when running as a license server (LICENSE_SERVER_MODE=true)
    
    # Server-managed licenses (subscription keys issued by admin)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS server_licenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            license_key TEXT UNIQUE NOT NULL,
            license_type TEXT NOT NULL CHECK(license_type IN ('trial', 'subscription', 'lifetime', 'beta')),
            customer_id TEXT,
            customer_email TEXT,
            customer_name TEXT,
            machine_id TEXT,
            machine_info TEXT,
            max_devices INTEGER DEFAULT 1,
            devices_used INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active' CHECK(status IN ('active', 'expired', 'revoked', 'suspended')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            activated_at TIMESTAMP,
            expires_at TIMESTAMP,
            last_validated_at TIMESTAMP,
            last_validated_ip TEXT,
            notes TEXT
        )
    ''')
    
    # Trial tracking (one trial per machine ID)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS server_trials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id TEXT UNIQUE NOT NULL,
            license_key TEXT NOT NULL,
            first_ip TEXT,
            user_agent TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            status TEXT DEFAULT 'active' CHECK(status IN ('active', 'expired', 'converted')),
            converted_to_license_id INTEGER,
            FOREIGN KEY (converted_to_license_id) REFERENCES server_licenses(id)
        )
    ''')
    
    # Machine tracking (for multi-device licenses)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS server_machines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            license_id INTEGER NOT NULL,
            machine_id TEXT NOT NULL,
            machine_name TEXT,
            machine_info TEXT,
            first_seen_ip TEXT,
            last_seen_ip TEXT,
            first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1,
            FOREIGN KEY (license_id) REFERENCES server_licenses(id),
            UNIQUE(license_id, machine_id)
        )
    ''')
    
    # License validation log (for analytics and abuse detection)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS license_validation_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            license_key TEXT,
            machine_id TEXT,
            action TEXT NOT NULL CHECK(action IN ('validate', 'activate', 'trial_request', 'revoke', 'deactivate')),
            result TEXT NOT NULL CHECK(result IN ('success', 'failed', 'blocked', 'rate_limited')),
            ip_address TEXT,
            user_agent TEXT,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Debug reports table for sending bug reports to admin
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS debug_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference_number TEXT UNIQUE NOT NULL,
            user_description TEXT,
            error_logs TEXT,
            system_info TEXT,
            email_sent INTEGER DEFAULT 0,
            email_sent_at TIMESTAMP,
            admin_email TEXT,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'sent', 'reviewed', 'resolved')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Trade monitor - track synced broker orders to prevent duplicate posts
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS synced_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            broker TEXT NOT NULL,
            order_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            quantity INTEGER,
            filled_price REAL,
            asset_type TEXT DEFAULT 'stock',
            strike REAL,
            expiry TEXT,
            direction TEXT,
            posted_to_discord INTEGER DEFAULT 0,
            discord_channel_id TEXT,
            synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(broker, order_id)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_synced_orders_broker ON synced_orders(broker)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_synced_orders_order_id ON synced_orders(broker, order_id)')
    
    # Trade monitor settings
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trade_monitor_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            enabled INTEGER DEFAULT 0,
            poll_interval_seconds INTEGER DEFAULT 10,
            target_webhook_channel_id TEXT,
            include_stocks INTEGER DEFAULT 1,
            include_options INTEGER DEFAULT 1,
            post_bto_signals INTEGER DEFAULT 1,
            post_stc_signals INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('INSERT OR IGNORE INTO trade_monitor_settings (id) VALUES (1)')
    
    # Signal Verification - Track and verify signals against real market data
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signal_verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER,
            channel_id INTEGER,
            user_id INTEGER,
            author_name TEXT,
            ticker TEXT NOT NULL,
            asset_type TEXT DEFAULT 'option',
            strike REAL,
            expiry TEXT,
            direction TEXT,
            signal_price REAL NOT NULL,
            signal_timestamp TIMESTAMP NOT NULL,
            market_bid REAL,
            market_ask REAL,
            market_last REAL,
            market_volume INTEGER,
            open_interest INTEGER,
            implied_volatility REAL,
            market_timestamp TIMESTAMP,
            price_difference REAL,
            slippage_pct REAL,
            within_spread INTEGER DEFAULT 0,
            executable INTEGER DEFAULT 0,
            execution_difficulty TEXT DEFAULT 'UNKNOWN',
            volume_liquidity TEXT DEFAULT 'UNKNOWN',
            verification_status TEXT DEFAULT 'PENDING',
            verification_notes TEXT,
            actual_fill_price REAL,
            actual_fill_time TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (signal_id) REFERENCES signals(id),
            FOREIGN KEY (channel_id) REFERENCES channels(id)
        )
    ''')
    # Migration: Add author_name column if missing (must run BEFORE creating index)
    try:
        cursor.execute('SELECT author_name FROM signal_verifications LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute('ALTER TABLE signal_verifications ADD COLUMN author_name TEXT')
        conn.commit()
        print("[DATABASE] ✓ Added author_name column to signal_verifications")
    
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_verifications_ticker ON signal_verifications(ticker)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_verifications_channel ON signal_verifications(channel_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_verifications_user ON signal_verifications(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_verifications_author ON signal_verifications(author_name)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_verifications_timestamp ON signal_verifications(signal_timestamp)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_verifications_status ON signal_verifications(verification_status)')
    
    # Verification summary stats per user/channel
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS verification_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL CHECK(entity_type IN ('user', 'channel')),
            entity_id TEXT NOT NULL,
            period_start TIMESTAMP NOT NULL,
            period_end TIMESTAMP NOT NULL,
            total_signals INTEGER DEFAULT 0,
            verified_signals INTEGER DEFAULT 0,
            executable_signals INTEGER DEFAULT 0,
            within_spread_signals INTEGER DEFAULT 0,
            avg_slippage_pct REAL DEFAULT 0,
            avg_price_difference REAL DEFAULT 0,
            high_volume_signals INTEGER DEFAULT 0,
            low_volume_signals INTEGER DEFAULT 0,
            suspicious_signals INTEGER DEFAULT 0,
            calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(entity_type, entity_id, period_start)
        )
    ''')
    
    # Signal Instances - Deduplication tracking to prevent duplicate entries on same trade
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signal_instances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL,
            ticker TEXT NOT NULL,
            entry_price REAL NOT NULL,
            direction TEXT NOT NULL,
            quantity INTEGER DEFAULT 1,
            remaining_qty INTEGER DEFAULT 1,
            author_id TEXT,
            author_name TEXT,
            fingerprint TEXT NOT NULL,
            status TEXT DEFAULT 'OPEN' CHECK(status IN ('OPEN', 'CLOSED', 'EXPIRED')),
            first_message_id TEXT,
            last_message_id TEXT,
            stop_loss REAL,
            profit_targets TEXT,
            update_count INTEGER DEFAULT 1,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            closed_at TIMESTAMP,
            close_reason TEXT,
            ttl_hours INTEGER DEFAULT 24,
            UNIQUE(channel_id, fingerprint)
        )
    ''')
    
    # Migrate: Add OMS/RMS columns to signal_instances for C1apped/WaxUI tracking
    try:
        cursor.execute('SELECT discord_message_id FROM signal_instances LIMIT 1')
    except sqlite3.OperationalError:
        cursor.execute('ALTER TABLE signal_instances ADD COLUMN discord_message_id TEXT')
        cursor.execute('ALTER TABLE signal_instances ADD COLUMN discord_channel_id TEXT')
        cursor.execute('ALTER TABLE signal_instances ADD COLUMN original_sl REAL')
        cursor.execute('ALTER TABLE signal_instances ADD COLUMN current_sl REAL')
        cursor.execute('ALTER TABLE signal_instances ADD COLUMN sl_order_id TEXT')
        cursor.execute('ALTER TABLE signal_instances ADD COLUMN pt_order_ids TEXT')
        cursor.execute('ALTER TABLE signal_instances ADD COLUMN entry_order_id TEXT')
        cursor.execute('ALTER TABLE signal_instances ADD COLUMN hit_level_count INTEGER DEFAULT 0')
        cursor.execute('ALTER TABLE signal_instances ADD COLUMN exit_processed INTEGER DEFAULT 0')
        cursor.execute('ALTER TABLE signal_instances ADD COLUMN exit_source TEXT')
        cursor.execute('ALTER TABLE signal_instances ADD COLUMN exit_strategy_mode TEXT')
        cursor.execute('ALTER TABLE signal_instances ADD COLUMN sl_version INTEGER DEFAULT 0')
        cursor.execute('ALTER TABLE signal_instances ADD COLUMN broker TEXT')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_instances_message_id ON signal_instances(discord_message_id)')
        conn.commit()
        print("[DATABASE] ✓ Added OMS/RMS columns to signal_instances for dynamic signal tracking")
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_instances_channel ON signal_instances(channel_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_instances_ticker ON signal_instances(ticker)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_instances_fingerprint ON signal_instances(fingerprint)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_instances_status ON signal_instances(status)')
    
    # Create indexes for license tables
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_server_licenses_key ON server_licenses(license_key)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_server_licenses_machine ON server_licenses(machine_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_server_licenses_status ON server_licenses(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_server_trials_machine ON server_trials(machine_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_server_machines_license ON server_machines(license_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_license_log_key ON license_validation_log(license_key)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_license_log_time ON license_validation_log(created_at)')
    
    # Filled Orders - Broker-synced filled order history
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS filled_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            broker TEXT NOT NULL,
            broker_order_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            asset_type TEXT DEFAULT 'option' CHECK(asset_type IN ('option', 'stock')),
            side TEXT NOT NULL CHECK(side IN ('BUY', 'SELL', 'BTO', 'STC')),
            quantity INTEGER NOT NULL,
            filled_price REAL NOT NULL,
            total_cost REAL,
            fees REAL DEFAULT 0,
            filled_at TIMESTAMP NOT NULL,
            strike REAL,
            expiry TEXT,
            option_type TEXT,
            channel_id TEXT,
            signal_id INTEGER,
            trade_id INTEGER,
            source TEXT DEFAULT 'broker_sync',
            synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(broker, broker_order_id)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_filled_orders_broker ON filled_orders(broker)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_filled_orders_symbol ON filled_orders(symbol)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_filled_orders_filled_at ON filled_orders(filled_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_filled_orders_channel ON filled_orders(channel_id)')
    
    # Broker sync state - Track last sync timestamps per broker
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS broker_sync_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            broker TEXT UNIQUE NOT NULL,
            last_sync_at TIMESTAMP,
            last_order_id TEXT,
            sync_cursor TEXT,
            error_count INTEGER DEFAULT 0,
            last_error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # ============================================
    # PROPORTIONAL POSITION SIZING & EXECUTION TRACKING TABLES
    # ============================================
    
    # Analyst Portfolios - Store analyst portfolio value per channel for proportional sizing
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS analyst_portfolios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL UNIQUE,
            portfolio_value REAL NOT NULL,
            currency TEXT DEFAULT 'USD',
            source TEXT DEFAULT 'manual',
            notes TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (channel_id) REFERENCES channels(discord_channel_id)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_analyst_portfolios_channel ON analyst_portfolios(channel_id)')
    
    # User Sizing Settings - User's position sizing preferences per channel
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_sizing_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT,
            sizing_mode TEXT NOT NULL DEFAULT 'fixed_contracts' CHECK(sizing_mode IN ('mirror', 'fixed_dollar', 'fixed_contracts')),
            fixed_dollar_amount REAL,
            fixed_contracts INTEGER,
            max_position_pct REAL DEFAULT 25.0,
            min_contracts INTEGER DEFAULT 1,
            max_contracts INTEGER,
            user_portfolio_value REAL,
            is_global INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(channel_id)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_sizing_channel ON user_sizing_settings(channel_id)')
    
    # Insert default global sizing settings
    cursor.execute('''
        INSERT OR IGNORE INTO user_sizing_settings (id, channel_id, sizing_mode, is_global)
        VALUES (1, NULL, 'fixed_contracts', 1)
    ''')
    
    # Execution Lots - Actual broker fills with timestamps and slippage tracking
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS execution_lots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_lot_id INTEGER,
            channel_id TEXT NOT NULL,
            broker TEXT NOT NULL,
            broker_order_id TEXT,
            symbol TEXT NOT NULL,
            asset_type TEXT NOT NULL CHECK(asset_type IN ('stock', 'option')),
            strike REAL,
            expiry TEXT,
            call_put TEXT,
            original_qty INTEGER NOT NULL,
            remaining_qty INTEGER NOT NULL,
            fill_price REAL NOT NULL,
            signal_price REAL,
            slippage_pct REAL,
            signal_detected_at TIMESTAMP,
            signal_parsed_at TIMESTAMP,
            order_submitted_at TIMESTAMP,
            order_filled_at TIMESTAMP NOT NULL,
            latency_parse_ms INTEGER,
            latency_broker_ms INTEGER,
            latency_total_ms INTEGER,
            analyst_entry_qty INTEGER,
            sizing_mode TEXT,
            sizing_details TEXT,
            status TEXT DEFAULT 'OPEN' CHECK(status IN ('OPEN', 'CLOSED', 'PARTIAL')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (signal_lot_id) REFERENCES signal_lots(id),
            UNIQUE(broker, broker_order_id)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_exec_lots_channel_status ON execution_lots(channel_id, status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_exec_lots_broker_filled ON execution_lots(broker, order_filled_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_exec_lots_signal_lot ON execution_lots(signal_lot_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_exec_lots_symbol ON execution_lots(symbol)')
    
    # Execution Closures - Actual exit fills with real P&L
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS execution_closures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_lot_id INTEGER NOT NULL,
            signal_lot_closure_id INTEGER,
            channel_id TEXT NOT NULL,
            broker TEXT NOT NULL,
            broker_order_id TEXT,
            closed_qty INTEGER NOT NULL,
            fill_price REAL NOT NULL,
            signal_exit_price REAL,
            slippage_pct REAL,
            order_submitted_at TIMESTAMP,
            filled_at TIMESTAMP NOT NULL,
            latency_broker_ms INTEGER,
            pnl REAL NOT NULL,
            pnl_percent REAL NOT NULL,
            holding_days REAL,
            exit_source TEXT NOT NULL CHECK(exit_source IN ('SIGNAL', 'PT1', 'PT2', 'PT3', 'PT4', 'STOP_LOSS', 'TRAILING', 'MANUAL', 'RISK')),
            closure_hash TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (execution_lot_id) REFERENCES execution_lots(id),
            FOREIGN KEY (signal_lot_closure_id) REFERENCES lot_closures(id)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_exec_closures_lot ON execution_closures(execution_lot_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_exec_closures_filled ON execution_closures(filled_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_exec_closures_channel ON execution_closures(channel_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_exec_closures_source ON execution_closures(exit_source)')
    
    # Pending Order Metadata - Bridge between order placement and BrokerSyncService
    # Stores signal context when orders are submitted so fills can be linked back
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_order_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            broker TEXT NOT NULL,
            broker_order_id TEXT,
            client_order_id TEXT,
            channel_id TEXT NOT NULL,
            message_id TEXT,
            signal_lot_id INTEGER,
            symbol TEXT NOT NULL,
            asset_type TEXT NOT NULL CHECK(asset_type IN ('stock', 'option')),
            action TEXT NOT NULL CHECK(action IN ('BTO', 'STC', 'BUY', 'SELL')),
            quantity INTEGER NOT NULL,
            signal_price REAL,
            analyst_qty INTEGER,
            sizing_mode TEXT,
            sizing_details TEXT,
            signal_detected_at TIMESTAMP,
            signal_parsed_at TIMESTAMP,
            order_submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'FILLED', 'CANCELLED', 'EXPIRED')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(broker, broker_order_id),
            FOREIGN KEY (signal_lot_id) REFERENCES signal_lots(id)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pending_meta_broker_order ON pending_order_metadata(broker, broker_order_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pending_meta_status ON pending_order_metadata(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pending_meta_channel ON pending_order_metadata(channel_id)')
    
    print("[DATABASE] ✓ Execution tracking tables ready")
    
    # Seed common known issues
    cursor.execute('''
        INSERT OR IGNORE INTO known_issues (id, error_pattern, issue_title, issue_description, solution, category, keywords)
        VALUES 
        (1, 'broker.*connect|connection.*refused|login.*failed', 'Broker Connection Failed', 
         'Unable to connect to your broker account. This usually means credentials are incorrect or the broker service is down.',
         'Go to Settings and verify your broker credentials are correct. For Webull, ensure your Trade PIN is exactly 6 digits. For Alpaca, check that your API keys are from the correct environment (paper vs live). Click "Test Connection" to verify.',
         'broker', 'webull,alpaca,ibkr,connection,login,credentials'),
        (2, 'discord.*token|unauthorized|invalid.*token', 'Discord Token Invalid',
         'Your Discord token is no longer valid. Tokens can expire or be invalidated by Discord.',
         'Get a new Discord token: 1) Open Discord in a browser, 2) Press F12 for Developer Tools, 3) Go to Network tab, 4) Filter for /api, 5) Find the Authorization header in any request. Paste the new token in Settings.',
         'discord', 'discord,token,unauthorized,auth'),
        (3, 'rate.*limit|too.*many.*requests|429', 'API Rate Limit Hit',
         'Too many requests sent to an API. The system is being throttled.',
         'Wait a few minutes before retrying. If this happens frequently, consider reducing the frequency of price refreshes or enabling longer cache times.',
         'api', 'rate,limit,api,throttle,429'),
        (4, 'insufficient.*funds|buying.*power|margin', 'Insufficient Buying Power',
         'Your account does not have enough funds to execute this trade.',
         'Check your account balance on the Dashboard. Either add funds to your brokerage account or reduce your position size in Settings.',
         'trading', 'funds,buying,power,margin,balance'),
        (5, 'option.*chain|expiration.*not.*found|no.*options', 'Option Data Unavailable',
         'Could not fetch option chain data for the requested symbol.',
         'Try a different expiration date or verify the symbol supports options. For SPX, ensure you are looking at the correct expiration format (daily vs monthly).',
         'options', 'options,chain,expiration,data'),
        (6, 'signal.*parse|invalid.*format|regex', 'Signal Format Not Recognized',
         'The trading signal could not be parsed. The format may not match expected patterns.',
         'Signals should follow formats like "BTO SPY 450C 12/15 @ 2.50" or "STC AAPL @ 150". Check Settings > Signal Patterns to see supported formats.',
         'signals', 'signal,parse,format,bto,stc'),
        (7, 'database|sqlite|locked|busy', 'Database Error',
         'A database operation failed. This can happen during high activity.',
         'Try refreshing the page. If the issue persists, restart the bot. Your data is safe.',
         'system', 'database,sqlite,error,locked')
    ''')
    
    # Create indexes for performance
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_channel ON trades(channel_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_executed_at ON trades(executed_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signals_channel ON signals(channel_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_lots_channel_symbol ON signal_lots(channel_id, asset_type, symbol, status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_lots_opened_at ON signal_lots(opened_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_lot_closures_channel ON lot_closures(channel_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_lot_closures_closed_at ON lot_closures(closed_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_channel_allowed_users_channel ON channel_allowed_users(channel_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_channel_allowed_users_user ON channel_allowed_users(discord_user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_waitlist_email ON waitlist(email)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_waitlist_status ON waitlist(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_waitlist_queue ON waitlist(queue_position)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_error_logs_type ON error_logs(error_type)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_error_logs_severity ON error_logs(severity)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_error_logs_last_seen ON error_logs(last_seen)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_error_logs_resolved ON error_logs(resolved)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_known_issues_category ON known_issues(category)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_debug_reports_ref ON debug_reports(reference_number)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_debug_reports_status ON debug_reports(status)')
    
    # Migration: Add user_id to signal_lots for user-based tracking
    try:
        cursor.execute('SELECT user_id FROM signal_lots LIMIT 1')
    except sqlite3.OperationalError:
        print("[DATABASE] Adding user_id column to signal_lots table...")
        cursor.execute('ALTER TABLE signal_lots ADD COLUMN user_id INTEGER')
        conn.commit()
        print("[DATABASE] ✓ User ID tracking column added to signal_lots")
    
    # Migration: Add user_id to lot_closures for user-based tracking
    try:
        cursor.execute('SELECT user_id FROM lot_closures LIMIT 1')
    except sqlite3.OperationalError:
        print("[DATABASE] Adding user_id column to lot_closures table...")
        cursor.execute('ALTER TABLE lot_closures ADD COLUMN user_id INTEGER')
        conn.commit()
        print("[DATABASE] ✓ User ID tracking column added to lot_closures")
    
    # Migration: Add exit_reason to lot_closures for tracking WHY positions were closed
    try:
        cursor.execute('SELECT exit_reason FROM lot_closures LIMIT 1')
    except sqlite3.OperationalError:
        print("[DATABASE] Adding exit_reason column to lot_closures table...")
        cursor.execute('ALTER TABLE lot_closures ADD COLUMN exit_reason TEXT')
        conn.commit()
        print("[DATABASE] ✓ Exit reason tracking column added to lot_closures")
    
    # Create GUI_EXEC channel for tracking GUI-originated trades (if not exists)
    cursor.execute("""
        INSERT OR IGNORE INTO channels (discord_channel_id, name, category, execute_enabled, track_enabled, is_active)
        VALUES ('GUI_EXEC', 'GUI Executions', 'EXECUTE', 1, 1, 1)
    """)
    if cursor.rowcount > 0:
        print("[DATABASE] ✓ Created GUI_EXEC channel for options page tracking")
    
    conn.commit()
    
    # Ensure signal verification tables exist
    ensure_signal_verification_tables()
    
    print("[DATABASE] ✓ Database initialized")

def ensure_signal_verification_tables():
    """Ensure signal verification tables exist (for local machine deployments)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signal_verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER,
            channel_id INTEGER,
            user_id INTEGER,
            author_name TEXT,
            ticker TEXT NOT NULL,
            asset_type TEXT DEFAULT 'option',
            strike REAL,
            expiry TEXT,
            direction TEXT,
            signal_price REAL NOT NULL,
            signal_timestamp TIMESTAMP NOT NULL,
            market_bid REAL,
            market_ask REAL,
            market_last REAL,
            market_volume INTEGER,
            open_interest INTEGER,
            implied_volatility REAL,
            market_timestamp TIMESTAMP,
            price_difference REAL,
            slippage_pct REAL,
            within_spread INTEGER DEFAULT 0,
            executable INTEGER DEFAULT 0,
            execution_difficulty TEXT DEFAULT 'UNKNOWN',
            volume_liquidity TEXT DEFAULT 'UNKNOWN',
            verification_status TEXT DEFAULT 'PENDING',
            verification_notes TEXT,
            actual_fill_price REAL,
            actual_fill_time TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_verifications_ticker ON signal_verifications(ticker)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_verifications_channel ON signal_verifications(channel_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_verifications_user ON signal_verifications(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_verifications_author ON signal_verifications(author_name)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_verifications_timestamp ON signal_verifications(signal_timestamp)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_signal_verifications_status ON signal_verifications(verification_status)')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS verification_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL CHECK(entity_type IN ('user', 'channel')),
            entity_id TEXT NOT NULL,
            period_start TIMESTAMP NOT NULL,
            period_end TIMESTAMP NOT NULL,
            total_signals INTEGER DEFAULT 0,
            verified_signals INTEGER DEFAULT 0,
            executable_signals INTEGER DEFAULT 0,
            within_spread_signals INTEGER DEFAULT 0,
            avg_slippage_pct REAL DEFAULT 0,
            avg_price_difference REAL DEFAULT 0,
            high_volume_signals INTEGER DEFAULT 0,
            low_volume_signals INTEGER DEFAULT 0,
            suspicious_signals INTEGER DEFAULT 0,
            calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(entity_type, entity_id, period_start)
        )
    ''')
    
    conn.commit()
    print("[DATABASE] ✓ Signal verification tables ready")

# ==================== USER MANAGEMENT ====================

def create_user(username: str, email: str, password: str) -> bool:
    """Create a new application user with hashed password"""
    import hashlib
    import os
    
    # Hash password with salt
    salt = os.urandom(32)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
    password_hash = (salt + pwd_hash).hex()
    
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO app_users (username, email, password_hash)
            VALUES (?, ?, ?)
        ''', (username, email, password_hash))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False

def verify_password(username: str, password: str) -> bool:
    """Verify username and password"""
    import hashlib
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT password_hash FROM app_users WHERE username = ?', (username,))
    row = cursor.fetchone()
    
    if not row:
        return False
    
    stored_hash_hex = row['password_hash']
    stored_hash = bytes.fromhex(stored_hash_hex)
    salt = stored_hash[:32]
    stored_pwd_hash = stored_hash[32:]
    
    pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
    return pwd_hash == stored_pwd_hash

def get_user_by_username(username: str) -> Dict:
    """Get user by username"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, username, email, is_admin FROM app_users WHERE username = ?', (username,))
    row = cursor.fetchone()
    return dict(row) if row else None

def user_exists() -> bool:
    """Check if any user exists (for setup wizard)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) as count FROM app_users')
    row = cursor.fetchone()
    return row['count'] > 0 if row else False

def create_password_reset_token(user_id: int) -> str:
    """Create a password reset token for user"""
    import secrets
    from datetime import datetime, timedelta
    
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now() + timedelta(hours=24)).isoformat()
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO password_reset_tokens (user_id, token, expires_at)
        VALUES (?, ?, ?)
    ''', (user_id, token, expires_at))
    conn.commit()
    return token

def verify_reset_token(token: str) -> Optional[int]:
    """Verify reset token and return user_id if valid"""
    from datetime import datetime
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id FROM password_reset_tokens
        WHERE token = ? AND expires_at > ?
    ''', (token, datetime.now().isoformat()))
    row = cursor.fetchone()
    return row['user_id'] if row else None

def reset_password(token: str, new_password: str) -> bool:
    """Reset password using token"""
    import hashlib
    import os
    
    user_id = verify_reset_token(token)
    if not user_id:
        return False
    
    # Hash new password
    salt = os.urandom(32)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', new_password.encode(), salt, 100000)
    password_hash = (salt + pwd_hash).hex()
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE app_users SET password_hash = ? WHERE id = ?
    ''', (password_hash, user_id))
    cursor.execute('DELETE FROM password_reset_tokens WHERE token = ?', (token,))
    conn.commit()
    return True

def get_user_email(username: str) -> Optional[str]:
    """Get user's email address"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT email FROM app_users WHERE username = ?', (username,))
    row = cursor.fetchone()
    return row['email'] if row else None


def create_local_recovery_code(username: str) -> Optional[Dict[str, str]]:
    """
    Create a local recovery code for password reset (for user builds without email).
    Generates a 6-digit code and saves it to a local file.
    Returns dict with 'code' and 'file_path' or None if user not found.
    """
    import secrets
    import os
    from datetime import datetime, timedelta
    from pathlib import Path
    
    user = get_user_by_username(username)
    if not user:
        return None
    
    code = f"{secrets.randbelow(1000000):06d}"
    expires_at = (datetime.now() + timedelta(minutes=15)).isoformat()
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO password_reset_tokens (user_id, token, expires_at)
        VALUES (?, ?, ?)
    ''', (user['id'], f"LOCAL:{code}", expires_at))
    conn.commit()
    
    import stat
    import tempfile
    
    recovery_dir = Path(tempfile.gettempdir()) / 'botifytrades_recovery'
    recovery_dir.mkdir(exist_ok=True, mode=0o700)
    
    recovery_file = recovery_dir / f'recovery_{secrets.token_hex(8)}.txt'
    
    with open(recovery_file, 'w') as f:
        f.write("=" * 50 + "\n")
        f.write("  BOTIFYTRADES PASSWORD RECOVERY CODE\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"  Username: {username}\n")
        f.write(f"  Recovery Code: {code}\n")
        f.write(f"  Expires: 15 minutes\n\n")
        f.write("  Enter this code on the password reset page.\n")
        f.write("  This file will be deleted after use.\n")
        f.write("=" * 50 + "\n")
    
    os.chmod(recovery_file, stat.S_IRUSR | stat.S_IWUSR)
    
    return {
        'code': code,
        'file_path': str(recovery_file),
        'username': username
    }


def verify_local_recovery_code(username: str, code: str) -> Optional[int]:
    """Verify local recovery code and return user_id if valid"""
    from datetime import datetime
    
    user = get_user_by_username(username)
    if not user:
        return None
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id FROM password_reset_tokens
        WHERE user_id = ? AND token = ? AND expires_at > ?
    ''', (user['id'], f"LOCAL:{code}", datetime.now().isoformat()))
    row = cursor.fetchone()
    return row['user_id'] if row else None


def reset_password_with_local_code(username: str, code: str, new_password: str) -> bool:
    """Reset password using local recovery code"""
    import hashlib
    import os
    import glob
    import tempfile
    from pathlib import Path
    
    user_id = verify_local_recovery_code(username, code)
    if not user_id:
        return False
    
    salt = os.urandom(32)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', new_password.encode(), salt, 100000)
    password_hash = (salt + pwd_hash).hex()
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE app_users SET password_hash = ? WHERE id = ?
    ''', (password_hash, user_id))
    cursor.execute('DELETE FROM password_reset_tokens WHERE user_id = ? AND token LIKE ?', 
                   (user_id, 'LOCAL:%'))
    conn.commit()
    
    recovery_dir = Path(tempfile.gettempdir()) / 'botifytrades_recovery'
    if recovery_dir.exists():
        try:
            for f in recovery_dir.glob('recovery_*.txt'):
                f.unlink()
        except:
            pass
    
    return True


# Channel management functions
def add_channel(discord_channel_id: str, name: str, category: str = None, execute_enabled: int = 0, track_enabled: int = 0, broker_override: Optional[str] = None, enabled_brokers = None, market: str = 'US'):
    """Add a new channel with dual-mode, multi-broker support, and market segmentation"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Backwards compatibility: if category is provided, set flags
    if category:
        execute_enabled = 1 if category == 'EXECUTE' else 0
        track_enabled = 1 if category == 'TRACK' else 0
    
    # Default category for legacy compatibility
    if not category:
        if execute_enabled and not track_enabled:
            category = 'EXECUTE'
        elif track_enabled and not execute_enabled:
            category = 'TRACK'
        elif execute_enabled and track_enabled:
            category = 'EXECUTE'  # Default to EXECUTE for dual-mode
        else:
            category = 'EXECUTE'  # Default fallback
    
    # Convert list to JSON string for database storage
    if isinstance(enabled_brokers, list):
        enabled_brokers = json.dumps(enabled_brokers)
    
    # Validate market code
    if market not in ('US', 'IN', 'CA'):
        market = 'US'
    
    try:
        cursor.execute('''
            INSERT INTO channels (discord_channel_id, name, category, execute_enabled, track_enabled, broker_override, enabled_brokers, market)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (discord_channel_id, name, category, execute_enabled, track_enabled, broker_override, enabled_brokers, market))
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None  # Channel already exists


def get_channels(category: Optional[str] = None, market: Optional[str] = None) -> List[Dict]:
    """Get all channels or filter by category/flags and/or market with signal statistics"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Build query with optional market filter
    conditions = []
    params = []
    
    if category == 'EXECUTE':
        conditions.append('execute_enabled = 1')
    elif category == 'TRACK':
        conditions.append('track_enabled = 1')
    elif category:
        conditions.append('category = ?')
        params.append(category)
    
    # Add market filter if provided (US, IN, CA)
    if market and market in ('US', 'IN', 'CA'):
        conditions.append('market = ?')
        params.append(market)
    
    # Build and execute query
    if conditions:
        query = f'SELECT * FROM channels WHERE {" AND ".join(conditions)} ORDER BY name'
        cursor.execute(query, params)
    else:
        cursor.execute('SELECT * FROM channels ORDER BY category, name')
    
    channels = [dict(row) for row in cursor.fetchall()]
    
    # Add signal statistics for each channel
    for channel in channels:
        channel_id = channel['id']
        
        # Total signals count
        cursor.execute('''
            SELECT COUNT(*) FROM signals WHERE channel_id = ?
        ''', (channel_id,))
        channel['total_signals'] = cursor.fetchone()[0]
        
        # Today's signals count
        cursor.execute('''
            SELECT COUNT(*) FROM signals 
            WHERE channel_id = ? AND DATE(received_at) = DATE('now')
        ''', (channel_id,))
        channel['signals_today'] = cursor.fetchone()[0]
        
        # Last signal received time
        cursor.execute('''
            SELECT received_at FROM signals 
            WHERE channel_id = ? ORDER BY received_at DESC LIMIT 1
        ''', (channel_id,))
        last_signal = cursor.fetchone()
        channel['last_signal_at'] = last_signal[0] if last_signal else None
    
    return channels


def get_channel_by_id(channel_id: int) -> Optional[Dict]:
    """Get a single channel by its internal ID with risk settings"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, discord_channel_id, name, category, execute_enabled, track_enabled,
               broker_override, is_active, paper_trade_enabled, enabled_brokers,
               profit_target_pct, profit_target_1_pct, profit_target_2_pct, profit_target_3_pct,
               stop_loss_pct, trailing_stop_pct, trailing_activation_pct, position_size_pct,
               created_at, updated_at, default_quantity, leave_runner_enabled, leave_runner_pct,
               profit_target_4_pct, profit_target_qty_1, profit_target_qty_2, profit_target_qty_3,
               profit_target_qty_4, trim_order_mode, trim_limit_offset, exit_strategy_mode, trade_summary_enabled,
               slippage_protection_enabled, slippage_max_pct
        FROM channels WHERE id = ?
    ''', (channel_id,))
    
    row = cursor.fetchone()
    if not row:
        return None
    
    return {
        'id': row[0],
        'discord_channel_id': row[1],
        'name': row[2],
        'category': row[3],
        'execute_enabled': row[4],
        'track_enabled': row[5],
        'broker_override': row[6],
        'is_active': row[7],
        'paper_trade_enabled': row[8],
        'enabled_brokers': json.loads(row[9]) if row[9] else [],
        'profit_target_pct': row[10],
        'profit_target_1_pct': row[11] if row[11] is not None else 20,
        'profit_target_2_pct': row[12] if row[12] is not None else 50,
        'profit_target_3_pct': row[13] if row[13] is not None else 100,
        'stop_loss_pct': row[14] if row[14] is not None else 10,
        'trailing_stop_pct': row[15],
        'trailing_activation_pct': row[16],
        'position_size_pct': row[17],
        'created_at': row[18],
        'updated_at': row[19],
        'default_quantity': row[20],
        'leave_runner_enabled': bool(row[21]) if row[21] is not None else False,
        'leave_runner_pct': row[22] if row[22] is not None else 25.0,
        'profit_target_4_pct': row[23],
        'profit_target_qty_1': row[24],
        'profit_target_qty_2': row[25],
        'profit_target_qty_3': row[26],
        'profit_target_qty_4': row[27],
        'trim_order_mode': row[28] if row[28] else 'market',
        'trim_limit_offset': row[29] if row[29] is not None else 0.01,
        'exit_strategy_mode': row[30] if row[30] else 'signal',
        'trade_summary_enabled': bool(row[31]) if len(row) > 31 and row[31] is not None else True,
        'slippage_protection_enabled': bool(row[32]) if len(row) > 32 and row[32] is not None else False,
        'slippage_max_pct': row[33] if len(row) > 33 else None
    }


def get_channel_by_discord_id(discord_channel_id: str) -> Optional[Dict]:
    """Get a single channel by its Discord channel ID with risk settings"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, discord_channel_id, name, category, execute_enabled, track_enabled,
               broker_override, is_active, paper_trade_enabled, enabled_brokers,
               profit_target_pct, profit_target_1_pct, profit_target_2_pct, profit_target_3_pct,
               stop_loss_pct, trailing_stop_pct, trailing_activation_pct, position_size_pct,
               created_at, updated_at, default_quantity, leave_runner_enabled, leave_runner_pct,
               profit_target_4_pct, profit_target_qty_1, profit_target_qty_2, profit_target_qty_3,
               profit_target_qty_4, trim_order_mode, trim_limit_offset, exit_strategy_mode, trade_summary_enabled,
               slippage_protection_enabled, slippage_max_pct
        FROM channels WHERE discord_channel_id = ?
    ''', (str(discord_channel_id),))
    
    row = cursor.fetchone()
    if not row:
        return None
    
    return {
        'id': row[0],
        'discord_channel_id': row[1],
        'name': row[2],
        'category': row[3],
        'execute_enabled': row[4],
        'track_enabled': row[5],
        'broker_override': row[6],
        'is_active': row[7],
        'paper_trade_enabled': row[8],
        'enabled_brokers': json.loads(row[9]) if row[9] else [],
        'profit_target_pct': row[10],
        'profit_target_1_pct': row[11] if row[11] is not None else 20,
        'profit_target_2_pct': row[12] if row[12] is not None else 50,
        'profit_target_3_pct': row[13] if row[13] is not None else 100,
        'stop_loss_pct': row[14] if row[14] is not None else 10,
        'trailing_stop_pct': row[15],
        'trailing_activation_pct': row[16],
        'position_size_pct': row[17],
        'created_at': row[18],
        'updated_at': row[19],
        'default_quantity': row[20],
        'leave_runner_enabled': bool(row[21]) if row[21] is not None else False,
        'leave_runner_pct': row[22] if row[22] is not None else 25.0,
        'profit_target_4_pct': row[23],
        'profit_target_qty_1': row[24],
        'profit_target_qty_2': row[25],
        'profit_target_qty_3': row[26],
        'profit_target_qty_4': row[27],
        'trim_order_mode': row[28] if row[28] else 'market',
        'trim_limit_offset': row[29] if row[29] is not None else 0.01,
        'exit_strategy_mode': row[30] if len(row) > 30 and row[30] else 'signal',
        'trade_summary_enabled': bool(row[31]) if len(row) > 31 and row[31] is not None else True,
        'slippage_protection_enabled': bool(row[32]) if len(row) > 32 and row[32] is not None else False,
        'slippage_max_pct': row[33] if len(row) > 33 else None
    }


def update_channel(channel_id: int, **kwargs):
    """Update channel fields (supports dual-mode flags)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    fields = []
    values = []
    
    for key, value in kwargs.items():
        if key in ['name', 'category', 'execute_enabled', 'track_enabled', 'broker_override', 'is_active', 
                   'paper_trade_enabled', 'profit_target_pct', 'profit_target_1_pct', 'profit_target_2_pct', 'profit_target_3_pct',
                   'profit_target_4_pct', 'profit_target_qty_1', 'profit_target_qty_2', 'profit_target_qty_3', 'profit_target_qty_4',
                   'stop_loss_pct', 'trailing_stop_pct', 'trailing_activation_pct', 'enabled_brokers', 'position_size_pct', 'tracking_position_size_pct',
                   'default_quantity', 'risk_management_enabled', 'leave_runner_enabled', 'leave_runner_pct',
                   'trim_order_mode', 'trim_limit_offset', 'exit_strategy_mode', 'market', 'trade_summary_enabled',
                   'conditional_order_timeout_minutes', 'trigger_offset_percent', 'order_timeout_minutes',
                   'slippage_protection_enabled', 'slippage_max_pct']:
            fields.append(f"{key} = ?")
            if key == 'enabled_brokers' and isinstance(value, list):
                values.append(json.dumps(value))
            else:
                values.append(value)
    
    # Sync category and execute_enabled/track_enabled flags bidirectionally
    if 'category' in kwargs and 'execute_enabled' not in kwargs and 'track_enabled' not in kwargs:
        # If category is being set, update flags accordingly
        category = kwargs['category']
        if category == 'EXECUTE':
            fields.append("execute_enabled = ?")
            values.append(1)
            fields.append("track_enabled = ?")
            values.append(0)
        elif category == 'TRACK':
            fields.append("execute_enabled = ?")
            values.append(0)
            fields.append("track_enabled = ?")
            values.append(1)
    elif ('execute_enabled' in kwargs or 'track_enabled' in kwargs) and 'category' not in kwargs:
        # When updating flags, get current state from database to determine new category
        cursor.execute('SELECT execute_enabled, track_enabled FROM channels WHERE id = ?', (channel_id,))
        current = cursor.fetchone()
        if current:
            current_execute = current[0] if current[0] is not None else 0
            current_track = current[1] if current[1] is not None else 0
            
            # Apply the updates being made
            new_execute = kwargs.get('execute_enabled', current_execute)
            new_track = kwargs.get('track_enabled', current_track)
            
            # Determine category based on combined state
            # Priority: EXECUTE > TRACK (if execute is enabled, category is EXECUTE)
            if new_execute == 1:
                fields.append("category = ?")
                values.append('EXECUTE')
            elif new_track == 1:
                fields.append("category = ?")
                values.append('TRACK')
            # If both are 0, don't change category (leave as last known state)
    
    if fields:
        values.append(datetime.now())
        values.append(channel_id)
        query = f"UPDATE channels SET {', '.join(fields)}, updated_at = ? WHERE id = ?"
        cursor.execute(query, values)
        conn.commit()
        return True
    return False


def delete_channel(channel_id: int):
    """Delete a channel"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM channels WHERE id = ?', (channel_id,))
    conn.commit()


def reset_channel_tracking(channel_id: int) -> Dict[str, int]:
    """Reset all tracking data for a channel (signals, lots, closures)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Count records before deletion
    cursor.execute('SELECT COUNT(*) FROM signals WHERE channel_id = ?', (channel_id,))
    signals_count = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM signal_lots WHERE channel_id = ?', (channel_id,))
    lots_count = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM lot_closures WHERE channel_id = ?', (channel_id,))
    closures_count = cursor.fetchone()[0]
    
    # Delete all related data
    cursor.execute('DELETE FROM lot_closures WHERE channel_id = ?', (channel_id,))
    cursor.execute('DELETE FROM signal_lots WHERE channel_id = ?', (channel_id,))
    cursor.execute('DELETE FROM signals WHERE channel_id = ?', (channel_id,))
    
    conn.commit()
    
    return {
        'signals': signals_count,
        'lots': lots_count,
        'closures': closures_count
    }


# Channel allowed users management functions
def add_allowed_user(channel_id: int, discord_user_id: str, discord_username: str) -> bool:
    """Add a user to the channel's allowed list"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO channel_allowed_users (channel_id, discord_user_id, discord_username)
            VALUES (?, ?, ?)
        ''', (channel_id, discord_user_id, discord_username))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def remove_allowed_user(channel_id: int, discord_user_id: str) -> bool:
    """Remove a user from the channel's allowed list"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        DELETE FROM channel_allowed_users
        WHERE channel_id = ? AND discord_user_id = ?
    ''', (channel_id, discord_user_id))
    conn.commit()
    
    return cursor.rowcount > 0


def get_allowed_users(channel_id: int) -> List[Dict]:
    """Get all allowed users for a specific channel"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, discord_user_id, discord_username, added_at
        FROM channel_allowed_users
        WHERE channel_id = ?
        ORDER BY discord_username
    ''', (channel_id,))
    
    return [dict(row) for row in cursor.fetchall()]


def is_user_allowed(channel_id: int, discord_user_id: str) -> bool:
    """
    Check if a user is allowed to execute/track in a channel.
    Returns True if:
    - No allowed users are configured (all users allowed)
    - User is in the allowed list
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Check if any allowed users are configured for this channel
    cursor.execute('''
        SELECT COUNT(*) FROM channel_allowed_users WHERE channel_id = ?
    ''', (channel_id,))
    
    total_allowed = cursor.fetchone()[0]
    
    # If no users configured, allow all users
    if total_allowed == 0:
        return True
    
    # Check if this specific user is allowed
    cursor.execute('''
        SELECT COUNT(*) FROM channel_allowed_users
        WHERE channel_id = ? AND discord_user_id = ?
    ''', (channel_id, discord_user_id))
    
    return cursor.fetchone()[0] > 0


def clear_allowed_users(channel_id: int) -> int:
    """Clear all allowed users for a channel (allow all users)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        DELETE FROM channel_allowed_users WHERE channel_id = ?
    ''', (channel_id,))
    conn.commit()
    
    return cursor.rowcount


# Trade management functions
def add_trade(signal_data: Dict) -> int:
    """Add a new trade to the database.
    
    For STC trades with origin_trade_id:
    - Stores original BTO entry price in intended_price (for ENTRY column display)
    - Stores exit price in executed_price (for CURRENT column display)
    - Calculates PNL from entry to exit
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    pnl = 0.0
    pnl_percent = 0.0
    intended_price = signal_data.get('intended_price')
    executed_price = signal_data.get('executed_price')
    
    # For STC trades linked to origin BTO, use original entry price for display
    if signal_data.get('direction') == 'STC' and signal_data.get('origin_trade_id'):
        try:
            cursor.execute('SELECT executed_price, asset_type FROM trades WHERE id = ?', 
                          (signal_data['origin_trade_id'],))
            origin = cursor.fetchone()
            if origin and origin[0]:
                entry_price = float(origin[0])
                exit_price = float(signal_data.get('executed_price') or signal_data.get('intended_price') or 0)
                qty = int(signal_data.get('quantity', 0))
                asset_type = origin[1] or signal_data.get('asset_type', 'option')
                
                # Store original entry price for ENTRY column, exit price for CURRENT column
                intended_price = entry_price
                executed_price = exit_price
                
                if entry_price > 0 and exit_price > 0 and qty > 0:
                    multiplier = 100 if asset_type == 'option' else 1
                    pnl = round((exit_price - entry_price) * qty * multiplier, 2)
                    pnl_percent = round(((exit_price - entry_price) / entry_price) * 100, 4) if entry_price else 0
                    print(f"[DATABASE] PNL calculated for STC: entry=${entry_price}, exit=${exit_price}, qty={qty}, pnl=${pnl} ({pnl_percent}%)")
        except Exception as e:
            print(f"[DATABASE] Error calculating STC PNL: {e}")
    
    cursor.execute('''
        INSERT INTO trades (
            channel_id, message_id, direction, asset_type, symbol,
            strike, expiry, call_put, quantity, intended_price,
            executed_price, executed_at, status, broker, order_id,
            stop_loss_price, profit_target_price, risk_trigger, origin_trade_id,
            user_id, source, pnl, pnl_percent, conditional_order_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        signal_data.get('channel_id'),
        signal_data.get('message_id'),
        signal_data['direction'],
        signal_data['asset_type'],
        signal_data['symbol'],
        signal_data.get('strike'),
        signal_data.get('expiry'),
        signal_data.get('call_put'),
        signal_data['quantity'],
        intended_price,
        executed_price,
        datetime.now() if signal_data.get('executed') else None,
        signal_data.get('status', 'PENDING'),
        signal_data.get('broker'),
        signal_data.get('order_id'),
        signal_data.get('stop_loss_price'),
        signal_data.get('profit_target_price'),
        signal_data.get('risk_trigger'),
        signal_data.get('origin_trade_id'),
        signal_data.get('user_id'),
        signal_data.get('source', 'discord'),
        pnl,
        pnl_percent,
        signal_data.get('conditional_order_id')
    ))
    
    conn.commit()
    return cursor.lastrowid


def get_trade_by_id(trade_id: int) -> Optional[Dict]:
    """Get a single trade by ID"""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM trades WHERE id = ?', (trade_id,))
        trade = cursor.fetchone()
        if trade:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, trade))
        return None
    except Exception as e:
        print(f"[DB] Error getting trade by ID {trade_id}: {e}")
        return None


def find_open_bto_trade(symbol: str, asset_type: str, broker: str = None,
                        strike: float = None, expiry: str = None, call_put: str = None) -> Optional[Dict]:
    """Find an open BTO trade for a position - used for risk management attribution.
    
    Returns the most recent open BTO trade matching the position criteria.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        if asset_type == 'option':
            # Generate expiry format variants for matching
            # Database may have: "12/17", "2025-12-17", "12/17/25", etc.
            expiry_variants = [expiry] if expiry else []
            if expiry:
                # If format is YYYY-MM-DD, also try MM/DD
                if '-' in expiry and len(expiry) == 10:
                    parts = expiry.split('-')
                    expiry_variants.append(f"{parts[1]}/{parts[2]}")  # 12/17
                    expiry_variants.append(f"{parts[1]}/{parts[2]}/{parts[0][2:]}")  # 12/17/25
                # If format is MM/DD, also try YYYY-MM-DD
                elif '/' in expiry and len(expiry) <= 5:
                    parts = expiry.split('/')
                    from datetime import datetime
                    year = datetime.now().year
                    expiry_variants.append(f"{year}-{parts[0].zfill(2)}-{parts[1].zfill(2)}")
            
            # Try each expiry variant
            for exp_try in expiry_variants:
                query = '''
                    SELECT id, channel_id, message_id, broker
                    FROM trades
                    WHERE symbol = ? AND asset_type = 'option' 
                    AND strike = ? AND expiry = ? AND call_put = ?
                    AND status = 'OPEN' AND direction = 'BTO'
                '''
                params = [symbol, strike, exp_try, call_put]
                if broker:
                    query += ' AND broker = ?'
                    params.append(broker)
                query += ' ORDER BY id DESC LIMIT 1'
                cursor.execute(query, params)
                row = cursor.fetchone()
                if row:
                    return {
                        'id': row[0],
                        'channel_id': row[1],
                        'message_id': row[2],
                        'broker': row[3]
                    }
            return None
        else:
            query = '''
                SELECT id, channel_id, message_id, broker
                FROM trades
                WHERE symbol = ? AND asset_type = 'stock'
                AND status = 'OPEN' AND direction = 'BTO'
            '''
            params = [symbol]
        
        if broker:
            query += ' AND broker = ?'
            params.append(broker)
        
        query += ' ORDER BY id DESC LIMIT 1'
        
        cursor.execute(query, params)
        row = cursor.fetchone()
        
        if row:
            return {
                'id': row[0],
                'channel_id': row[1],
                'message_id': row[2],
                'broker': row[3]
            }
        return None
    except Exception as e:
        print(f"[DB] Error finding open BTO trade: {e}")
        return None

def get_trades(status: Optional[str] = None, broker: Optional[str] = None, limit: int = 100) -> List[Dict]:
    """Get trades with optional filters and risk settings"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
        SELECT t.*, c.name as channel_name,
               r.profit_target_percent as profit_target_percent,
               r.stop_loss_percent as stop_loss_percent,
               r.trailing_stop_enabled as trailing_stop_enabled,
               r.trailing_stop_percent as trailing_stop_percent
        FROM trades t 
        LEFT JOIN channels c ON t.channel_id = c.discord_channel_id
        LEFT JOIN position_risk_settings r ON t.id = r.trade_id
        WHERE 1=1
    '''
    params = []
    
    if status:
        query += ' AND t.status = ?'
        params.append(status)
    
    if broker:
        # Case-insensitive broker matching (Webull vs WEBULL, ALPACA_PAPER vs alpaca_paper)
        query += ' AND LOWER(t.broker) = LOWER(?)'
        params.append(broker)
    
    query += ' ORDER BY t.executed_at DESC LIMIT ?'
    params.append(limit)
    
    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def get_all_broker_performance(period: str = 'all', broker_filter: str = None, user_id: int = None) -> Dict[str, Any]:
    """
    Get trading performance from ALL broker positions (trades table).
    NOT filtered by channel - shows all open/closed trades across all brokers.
    
    Args:
        period: 'today', '7d', '30d', 'year', 'all'
        broker_filter: Optional broker filter ('Webull', 'ALPACA_PAPER', etc.)
        user_id: Optional user ID filter (shows all if NULL due to historical trades)
    
    Returns:
        Dict with performance metrics from trades table directly
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Build date filter
    start_date, end_date = get_date_filter_bounds(period)
    
    params = []
    date_filter = ""
    if start_date and end_date:
        date_filter = "AND (t.executed_at BETWEEN ? AND ? OR t.closed_at BETWEEN ? AND ?)"
        params.extend([start_date, end_date, start_date, end_date])
    
    broker_clause = ""
    if broker_filter:
        broker_clause = "AND LOWER(t.broker) = LOWER(?)"
        params.append(broker_filter)
    
    # User filter - show all trades where user_id is NULL (historical) or matches current user
    user_clause = ""
    if user_id:
        user_clause = "AND (t.user_id IS NULL OR t.user_id = ?)"
        params.append(user_id)
    
    # Get CLOSED trades performance (realized P&L)
    closed_query = f'''
        SELECT 
            COUNT(*) as total_closed,
            SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN t.pnl <= 0 THEN 1 ELSE 0 END) as losses,
            COALESCE(SUM(t.pnl), 0) as realized_pnl,
            COALESCE(SUM(CASE WHEN t.pnl > 0 THEN t.pnl ELSE 0 END), 0) as gross_profit,
            COALESCE(SUM(CASE WHEN t.pnl < 0 THEN t.pnl ELSE 0 END), 0) as gross_loss,
            COALESCE(AVG(t.pnl), 0) as avg_pnl,
            COALESCE(AVG(t.pnl_percent), 0) as avg_pnl_percent,
            COALESCE(MAX(t.pnl), 0) as best_trade,
            COALESCE(MIN(t.pnl), 0) as worst_trade
        FROM trades t
        WHERE t.status = 'CLOSED' {date_filter} {broker_clause} {user_clause}
    '''
    
    cursor.execute(closed_query, tuple(params))
    closed_row = cursor.fetchone()
    
    # Get OPEN trades (unrealized P&L)
    open_params = []
    open_broker_clause = ""
    if broker_filter:
        open_broker_clause = "AND LOWER(t.broker) = LOWER(?)"
        open_params.append(broker_filter)
    
    open_user_clause = ""
    if user_id:
        open_user_clause = "AND (t.user_id IS NULL OR t.user_id = ?)"
        open_params.append(user_id)
    
    open_query = f'''
        SELECT 
            COUNT(*) as total_open,
            COALESCE(SUM(t.pnl), 0) as unrealized_pnl,
            COALESCE(SUM(t.quantity * t.executed_price * 100), 0) as total_invested
        FROM trades t
        WHERE t.status = 'OPEN' {open_broker_clause} {open_user_clause}
    '''
    
    cursor.execute(open_query, tuple(open_params))
    open_row = cursor.fetchone()
    
    total_closed = closed_row['total_closed'] or 0
    wins = closed_row['wins'] or 0
    losses = closed_row['losses'] or 0
    
    result = {
        'total_closed': total_closed,
        'total_open': open_row['total_open'] or 0,
        'total_trades': total_closed + (open_row['total_open'] or 0),
        'wins': wins,
        'losses': losses,
        'win_rate': round((wins / total_closed * 100) if total_closed > 0 else 0, 1),
        'realized_pnl': round(float(closed_row['realized_pnl'] or 0), 2),
        'unrealized_pnl': round(float(open_row['unrealized_pnl'] or 0), 2),
        'total_pnl': round(float(closed_row['realized_pnl'] or 0) + float(open_row['unrealized_pnl'] or 0), 2),
        'gross_profit': round(float(closed_row['gross_profit'] or 0), 2),
        'gross_loss': round(float(closed_row['gross_loss'] or 0), 2),
        'avg_pnl': round(float(closed_row['avg_pnl'] or 0), 2),
        'avg_pnl_percent': round(float(closed_row['avg_pnl_percent'] or 0), 1),
        'best_trade': round(float(closed_row['best_trade'] or 0), 2),
        'worst_trade': round(float(closed_row['worst_trade'] or 0), 2),
        'total_invested': round(float(open_row['total_invested'] or 0), 2),
        'profit_factor': 0.0
    }
    
    # Calculate profit factor
    if result['gross_loss'] != 0:
        result['profit_factor'] = round(abs(result['gross_profit'] / result['gross_loss']), 2)
    elif result['gross_profit'] > 0:
        result['profit_factor'] = 10.0
    
    return result


def get_all_broker_trades(status: Optional[str] = None, broker: Optional[str] = None, 
                          symbol: Optional[str] = None, limit: int = 200, user_id: int = None) -> Dict[str, Any]:
    """
    Get ALL trades from ALL brokers - not filtered by channel.
    Returns trades and filter metadata for UI dropdowns.
    
    Args:
        user_id: Optional user ID filter (shows all if NULL due to historical trades)
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
        SELECT t.id, t.symbol, t.strike, t.expiry, t.call_put, t.direction, t.quantity,
               t.executed_price as price, t.current_price, t.pnl, t.pnl_percent, t.status, t.broker,
               t.asset_type, t.option_id, t.executed_at, t.closed_at, t.channel_id,
               t.message_id, t.source,
               COALESCE(c.name, '') as channel_name, 
               COALESCE(c.category, '') as channel_category
        FROM trades t 
        LEFT JOIN channels c ON t.channel_id = c.discord_channel_id
        WHERE 1=1
    '''
    params = []
    
    # User filter - show all trades where user_id is NULL (historical) or matches current user
    if user_id:
        query += ' AND (t.user_id IS NULL OR t.user_id = ?)'
        params.append(user_id)
    
    if status:
        query += ' AND t.status = ?'
        params.append(status)
    
    if broker:
        query += ' AND LOWER(t.broker) = LOWER(?)'
        params.append(broker)
    
    if symbol:
        query += ' AND UPPER(t.symbol) LIKE ?'
        params.append(f'%{symbol.upper()}%')
    
    query += ' ORDER BY t.executed_at DESC LIMIT ?'
    params.append(limit)
    
    cursor.execute(query, params)
    trades = [dict(row) for row in cursor.fetchall()]
    
    # Get filter metadata
    cursor.execute('SELECT DISTINCT broker FROM trades WHERE broker IS NOT NULL ORDER BY broker')
    brokers = [row['broker'] for row in cursor.fetchall()]
    
    cursor.execute('SELECT DISTINCT status FROM trades WHERE status IS NOT NULL ORDER BY status')
    statuses = [row['status'] for row in cursor.fetchall()]
    
    cursor.execute('SELECT DISTINCT symbol FROM trades WHERE symbol IS NOT NULL ORDER BY symbol')
    symbols = [row['symbol'] for row in cursor.fetchall()]
    
    return {
        'trades': trades,
        'filters': {
            'brokers': brokers,
            'statuses': statuses,
            'symbols': symbols
        },
        'total': len(trades)
    }


def get_bot_trades(channel_id: Optional[str] = None, symbol: Optional[str] = None, 
                   status: Optional[str] = None, broker: Optional[str] = None, 
                   limit: int = 200) -> Dict[str, Any]:
    """
    Get ONLY bot-executed trades (trades with channel_id) - isolated from broker sync.
    Returns trades and filter metadata for UI dropdowns.
    Uses LEFT JOIN to include trades even if channel was deleted (shows as 'Unknown').
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
        SELECT t.id, t.symbol, t.strike, t.expiry, t.call_put, t.direction, t.quantity,
               t.executed_price as price, t.current_price, t.pnl, t.pnl_percent, t.status, t.broker,
               t.asset_type, t.option_id, t.executed_at, t.closed_at, t.channel_id,
               t.message_id, t.source,
               COALESCE(c.name, 'Unknown') as channel_name, 
               COALESCE(c.category, '') as channel_category
        FROM trades t 
        LEFT JOIN channels c ON t.channel_id = c.discord_channel_id
        WHERE t.channel_id IS NOT NULL AND t.channel_id != ''
    '''
    params = []
    
    if channel_id:
        query += ' AND t.channel_id = ?'
        params.append(channel_id)
    
    if symbol:
        query += ' AND UPPER(t.symbol) LIKE ?'
        params.append(f'%{symbol.upper()}%')
    
    if status:
        query += ' AND t.status = ?'
        params.append(status)
    
    if broker:
        query += ' AND t.broker = ?'
        params.append(broker)
    
    query += ' ORDER BY t.executed_at DESC LIMIT ?'
    params.append(limit)
    
    cursor.execute(query, params)
    trades = [dict(row) for row in cursor.fetchall()]
    
    channel_query = '''
        SELECT DISTINCT c.discord_channel_id, c.name, c.category, 
               COUNT(t.id) as trade_count
        FROM channels c
        INNER JOIN trades t ON c.discord_channel_id = t.channel_id
        WHERE t.channel_id IS NOT NULL AND t.channel_id != ''
        GROUP BY c.discord_channel_id, c.name, c.category
        ORDER BY trade_count DESC
    '''
    cursor.execute(channel_query)
    channels = [dict(row) for row in cursor.fetchall()]
    
    symbol_query = '''
        SELECT DISTINCT UPPER(symbol) as symbol, COUNT(*) as count
        FROM trades 
        WHERE channel_id IS NOT NULL AND channel_id != ''
        GROUP BY UPPER(symbol)
        ORDER BY count DESC
        LIMIT 50
    '''
    cursor.execute(symbol_query)
    symbols = [row['symbol'] for row in cursor.fetchall()]
    
    return {
        'trades': trades,
        'filters': {
            'channels': channels,
            'symbols': symbols,
            'statuses': ['OPEN', 'CLOSED', 'PENDING', 'CANCELLED'],
            'brokers': ['WEBULL', 'WEBULL_PAPER', 'ALPACA', 'ALPACA_PAPER', 'IBKR', 'IBKR_PAPER', 'ROBINHOOD']
        }
    }


def update_trade_price(trade_id: int, current_price: float, pnl: float, pnl_percent: float):
    """Update trade's current price and P&L"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE trades
        SET current_price = ?, pnl = ?, pnl_percent = ?
        WHERE id = ?
    ''', (current_price, pnl, pnl_percent, trade_id))
    
    conn.commit()


def close_trade(trade_id: int, close_price: float, pnl: float, pnl_percent: float):
    """Mark trade as closed"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE trades
        SET status = 'CLOSED', current_price = ?, pnl = ?, pnl_percent = ?, closed_at = ?
        WHERE id = ?
    ''', (close_price, pnl, pnl_percent, datetime.now(), trade_id))
    
    conn.commit()


def sync_positions_with_broker(broker_name: str, active_position_keys: set, user_id: int = None):
    """
    Sync database trades with broker positions.
    Marks trades as CLOSED if they're no longer open at the broker.
    
    Args:
        broker_name: The broker name (e.g., 'Webull', 'ALPACA_PAPER', 'ALPACA_LIVE')
        active_position_keys: Set of position keys currently open at broker
                             Format: {SYMBOL} for stocks, {SYMBOL}_{STRIKE}_{EXPIRY}_{C/P} for options
        user_id: Optional user ID filter
    
    Returns:
        Dict with sync results
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    user_clause = ""
    params = [broker_name]
    if user_id:
        user_clause = "AND (user_id IS NULL OR user_id = ?)"
        params.append(user_id)
    
    cursor.execute(f'''
        SELECT id, symbol, strike, expiry, call_put, asset_type, executed_price, quantity
        FROM trades
        WHERE status = 'OPEN' AND LOWER(broker) = LOWER(?) {user_clause}
    ''', params)
    
    open_trades = cursor.fetchall()
    closed_count = 0
    closed_trades = []
    
    for trade in open_trades:
        trade_id = trade['id']
        symbol = trade['symbol']
        strike = trade['strike']
        expiry = trade['expiry']
        call_put = trade['call_put']
        asset_type = trade['asset_type']
        entry_price = trade['executed_price'] or 0
        
        if asset_type == 'option' and strike and expiry and call_put:
            exp_normalized = expiry.replace('-', '') if expiry else ''
            if len(exp_normalized) == 8:
                exp_normalized = exp_normalized[4:8]
            position_key = f"{symbol}_{strike}_{exp_normalized}_{call_put}"
        else:
            position_key = symbol
        
        if position_key not in active_position_keys:
            pnl = 0.0
            pnl_percent = 0.0
            
            cursor.execute('''
                UPDATE trades
                SET status = 'CLOSED', closed_at = ?, pnl = ?, pnl_percent = ?
                WHERE id = ?
            ''', (datetime.now(), pnl, pnl_percent, trade_id))
            closed_count += 1
            closed_trades.append({
                'id': trade_id,
                'symbol': symbol,
                'position_key': position_key
            })
            print(f"[SYNC] Marked trade {trade_id} ({position_key}) as CLOSED - no longer at broker")
    
    if closed_count > 0:
        conn.commit()
    
    return {
        'broker': broker_name,
        'open_in_db': len(open_trades),
        'active_at_broker': len(active_position_keys),
        'closed': closed_count,
        'closed_trades': closed_trades
    }


def get_open_trades_for_broker(broker_name: str, user_id: int = None) -> list:
    """Get all OPEN trades for a specific broker"""
    conn = get_connection()
    cursor = conn.cursor()
    
    user_clause = ""
    params = [broker_name]
    if user_id:
        user_clause = "AND (user_id IS NULL OR user_id = ?)"
        params.append(user_id)
    
    cursor.execute(f'''
        SELECT id, symbol, strike, expiry, call_put, asset_type, executed_price, quantity, direction
        FROM trades
        WHERE status = 'OPEN' AND LOWER(broker) = LOWER(?) {user_clause}
    ''', params)
    
    return [dict(row) for row in cursor.fetchall()]


def find_open_trade_for_stc(broker_name: str, symbol: str, strike: float = None, 
                             expiry: str = None, call_put: str = None, 
                             asset_type: str = 'option') -> Optional[Dict]:
    """Find a matching open BTO trade for an STC order.
    
    Matches on symbol, strike, expiry, call_put for options.
    Returns the oldest matching open trade (FIFO).
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    if asset_type == 'option' and strike is not None:
        cursor.execute('''
            SELECT id, symbol, strike, expiry, call_put, asset_type, 
                   executed_price, quantity, direction, broker, source
            FROM trades
            WHERE status = 'OPEN' 
              AND LOWER(broker) = LOWER(?)
              AND UPPER(symbol) = UPPER(?)
              AND strike = ?
              AND UPPER(call_put) = UPPER(?)
              AND direction = 'BTO'
            ORDER BY executed_at ASC
            LIMIT 1
        ''', (broker_name, symbol, strike, call_put[0].upper() if call_put else 'C'))
    else:
        cursor.execute('''
            SELECT id, symbol, asset_type, executed_price, quantity, direction, broker, source
            FROM trades
            WHERE status = 'OPEN' 
              AND LOWER(broker) = LOWER(?)
              AND UPPER(symbol) = UPPER(?)
              AND direction = 'BTO'
            ORDER BY executed_at ASC
            LIMIT 1
        ''', (broker_name, symbol))
    
    row = cursor.fetchone()
    return dict(row) if row else None


def update_trade(trade_id: int, **kwargs):
    """Generic function to update any trade fields"""
    if not kwargs:
        return
    
    conn = get_connection()
    cursor = conn.cursor()
    
    # Build dynamic UPDATE query
    set_clause = ', '.join([f"{key} = ?" for key in kwargs.keys()])
    values = list(kwargs.values()) + [trade_id]
    
    query = f'''
        UPDATE trades
        SET {set_clause}
        WHERE id = ?
    '''
    
    cursor.execute(query, values)
    conn.commit()


def save_trailing_state(trade_id: int, trailing_activated: bool, highest_price: float, activated_at=None):
    """Save trailing stop state to database for persistence across restarts."""
    from datetime import datetime
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE trades
        SET trailing_activated = ?,
            highest_price = ?,
            trailing_activated_at = ?
        WHERE id = ?
    ''', (1 if trailing_activated else 0, highest_price, activated_at or datetime.now(), trade_id))
    
    conn.commit()
    print(f"[DATABASE] ✓ Saved trailing state for trade #{trade_id}: activated={trailing_activated}, highest=${highest_price:.2f}")


def get_trailing_state(trade_id: int) -> dict:
    """Get trailing stop state from database."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT trailing_activated, highest_price, trailing_activated_at
        FROM trades
        WHERE id = ?
    ''', (trade_id,))
    
    row = cursor.fetchone()
    if row:
        return {
            'trailing_activated': bool(row[0]),
            'highest_price': row[1],
            'trailing_activated_at': row[2]
        }
    return {'trailing_activated': False, 'highest_price': None, 'trailing_activated_at': None}


def get_open_trades_with_trailing_state():
    """Get all open trades with trailing stop state for RiskManager initialization."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, symbol, broker, strike, expiry, call_put, asset_type,
               executed_price, quantity, channel_id, trailing_activated, highest_price
        FROM trades
        WHERE status = 'OPEN' AND direction = 'BTO'
    ''')
    
    trades = []
    for row in cursor.fetchall():
        trades.append({
            'id': row[0],
            'symbol': row[1],
            'broker': row[2],
            'strike': row[3],
            'expiry': row[4],
            'call_put': row[5],
            'asset_type': row[6],
            'entry_price': row[7],
            'quantity': row[8],
            'channel_id': row[9],
            'trailing_activated': bool(row[10]) if row[10] else False,
            'highest_price': row[11]
        })
    
    return trades


# Lot management functions for PNL tracking
def create_signal_lot(channel_id: int, signal_id: int, asset_type: str, symbol: str, quantity: int, open_price: float, opened_at, strike: float = None, expiry: str = None, call_put: str = None, author_name: str = None, user_id: int = None):
    """Create a new signal lot from a BTO signal with author and user attribution"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO signal_lots (
            channel_id, signal_id, asset_type, symbol, strike, expiry, call_put,
            original_qty, remaining_qty, open_price, opened_at, status, source, author_name, user_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', 'SIGNAL', ?, ?)
    ''', (channel_id, signal_id, asset_type, symbol, strike, expiry, call_put, quantity, quantity, open_price, opened_at, author_name, user_id))
    
    conn.commit()
    return cursor.lastrowid


def get_open_lots(channel_id: int, asset_type: str, symbol: str, strike: float = None, expiry: str = None, call_put: str = None):
    """Get open lots for a symbol (FIFO order)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    if asset_type == 'option':
        cursor.execute('''
            SELECT * FROM signal_lots
            WHERE channel_id = ? AND asset_type = ? AND symbol = ?
            AND strike = ? AND expiry = ? AND call_put = ?
            AND status IN ('OPEN', 'PARTIAL')
            ORDER BY opened_at ASC
        ''', (channel_id, asset_type, symbol, strike, expiry, call_put))
    else:
        cursor.execute('''
            SELECT * FROM signal_lots
            WHERE channel_id = ? AND asset_type = ? AND symbol = ?
            AND status IN ('OPEN', 'PARTIAL')
            ORDER BY opened_at ASC
        ''', (channel_id, asset_type, symbol))
    
    return cursor.fetchall()


def get_most_recent_open_lot(channel_id: int, asset_type: str = None):
    """Get the most recently opened lot from a channel (for position matching on 'stopped out' signals).
    
    This is used when an exit signal (like 'stopped out') doesn't include contract details,
    and we need to match it to the most recent open position from that channel.
    
    Args:
        channel_id: The Discord channel ID
        asset_type: Optional filter by asset type ('option' or 'stock')
    
    Returns:
        The most recently opened lot that's still open, or None if no open positions
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    if asset_type:
        cursor.execute('''
            SELECT * FROM signal_lots
            WHERE channel_id = ? AND asset_type = ?
            AND status IN ('OPEN', 'PARTIAL')
            ORDER BY opened_at DESC
            LIMIT 1
        ''', (channel_id, asset_type))
    else:
        cursor.execute('''
            SELECT * FROM signal_lots
            WHERE channel_id = ?
            AND status IN ('OPEN', 'PARTIAL')
            ORDER BY opened_at DESC
            LIMIT 1
        ''', (channel_id,))
    
    return cursor.fetchone()


def get_all_open_lots_for_channel(channel_id: int):
    """Get all open lots for a channel (for displaying positions or bulk closing).
    
    Args:
        channel_id: The Discord channel ID
    
    Returns:
        List of all open/partial lots for the channel, ordered by most recent first
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM signal_lots
        WHERE channel_id = ?
        AND status IN ('OPEN', 'PARTIAL')
        ORDER BY opened_at DESC
    ''', (channel_id,))
    
    return cursor.fetchall()


def close_lot(lot_id: int, channel_id: int, signal_id: int, close_qty: int, close_price: float, closed_at, exit_reason: str = None):
    """Close a lot (fully or partially) and record PNL
    
    Args:
        exit_reason: Why the position was closed (e.g., 'PT1', 'STOP_LOSS', 'TRAILING_STOP', 'MANUAL')
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get lot details
    cursor.execute('SELECT * FROM signal_lots WHERE id = ?', (lot_id,))
    lot = cursor.fetchone()
    
    if not lot:
        return None
    
    # Calculate PNL with proper rounding to avoid floating point precision issues
    cost_basis = lot['open_price'] * close_qty
    if lot['asset_type'] == 'option':
        cost_basis *= 100  # Options contract multiplier
        proceeds = close_price * close_qty * 100
    else:
        proceeds = close_price * close_qty
    
    pnl = round(proceeds - cost_basis, 2)  # Round to 2 decimal places
    pnl_percent = round((pnl / cost_basis * 100), 4) if cost_basis > 0 else 0  # Round to 4 decimal places
    
    # Calculate holding period
    from datetime import datetime
    if isinstance(closed_at, str):
        closed_dt = datetime.fromisoformat(closed_at)
    else:
        closed_dt = closed_at
    
    if isinstance(lot['opened_at'], str):
        opened_dt = datetime.fromisoformat(lot['opened_at'])
    else:
        opened_dt = lot['opened_at']
    
    holding_days = (closed_dt - opened_dt).total_seconds() / 86400
    
    # Record closure (inherit author_name and user_id from lot for attribution)
    author_name = lot['author_name'] if 'author_name' in lot.keys() else None
    user_id = lot['user_id'] if 'user_id' in lot.keys() else None
    cursor.execute('''
        INSERT INTO lot_closures (
            lot_id, channel_id, signal_id, closed_qty, close_price,
            closed_at, pnl, pnl_percent, holding_days, author_name, user_id, exit_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (lot_id, channel_id, signal_id, close_qty, close_price, closed_at, pnl, pnl_percent, holding_days, author_name, user_id, exit_reason))
    
    # Update lot status
    new_remaining = lot['remaining_qty'] - close_qty
    if new_remaining <= 0:
        cursor.execute('UPDATE signal_lots SET remaining_qty = 0, status = "CLOSED" WHERE id = ?', (lot_id,))
    else:
        cursor.execute('UPDATE signal_lots SET remaining_qty = ?, status = "PARTIAL" WHERE id = ?', (new_remaining, lot_id))
    
    conn.commit()
    return cursor.lastrowid


# ============================================
# EXECUTION TRACKING FUNCTIONS
# ============================================

def create_execution_lot(
    signal_lot_id: int,
    channel_id: str,
    broker: str,
    broker_order_id: str,
    symbol: str,
    asset_type: str,
    quantity: int,
    fill_price: float,
    order_filled_at,
    signal_price: float = None,
    strike: float = None,
    expiry: str = None,
    call_put: str = None,
    signal_detected_at = None,
    signal_parsed_at = None,
    order_submitted_at = None,
    analyst_entry_qty: int = None,
    sizing_mode: str = None,
    sizing_details: str = None
):
    """Create an execution lot record for actual broker fills"""
    import hashlib
    from datetime import datetime
    
    conn = get_connection()
    cursor = conn.cursor()
    
    slippage_pct = None
    if signal_price and signal_price > 0:
        slippage_pct = round(((fill_price - signal_price) / signal_price) * 100, 4)
    
    latency_parse_ms = None
    latency_broker_ms = None
    latency_total_ms = None
    
    def to_datetime(ts):
        if ts is None:
            return None
        if isinstance(ts, datetime):
            return ts
        return datetime.fromisoformat(str(ts))
    
    detected_dt = to_datetime(signal_detected_at)
    parsed_dt = to_datetime(signal_parsed_at)
    submitted_dt = to_datetime(order_submitted_at)
    filled_dt = to_datetime(order_filled_at)
    
    if detected_dt and parsed_dt:
        latency_parse_ms = int((parsed_dt - detected_dt).total_seconds() * 1000)
    if submitted_dt and filled_dt:
        latency_broker_ms = int((filled_dt - submitted_dt).total_seconds() * 1000)
    if detected_dt and filled_dt:
        latency_total_ms = int((filled_dt - detected_dt).total_seconds() * 1000)
    
    try:
        cursor.execute('''
            INSERT INTO execution_lots (
                signal_lot_id, channel_id, broker, broker_order_id, symbol, asset_type,
                strike, expiry, call_put, original_qty, remaining_qty, fill_price,
                signal_price, slippage_pct, signal_detected_at, signal_parsed_at,
                order_submitted_at, order_filled_at, latency_parse_ms, latency_broker_ms,
                latency_total_ms, analyst_entry_qty, sizing_mode, sizing_details, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
        ''', (
            signal_lot_id, str(channel_id), broker, broker_order_id, symbol, asset_type,
            strike, expiry, call_put, quantity, quantity, fill_price,
            signal_price, slippage_pct, signal_detected_at, signal_parsed_at,
            order_submitted_at, order_filled_at, latency_parse_ms, latency_broker_ms,
            latency_total_ms, analyst_entry_qty, sizing_mode, sizing_details
        ))
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        print(f"[DATABASE] Error creating execution lot: {e}")
        return None


def get_open_execution_lots(channel_id: str = None, broker: str = None, symbol: str = None):
    """Get open execution lots with optional filtering"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = 'SELECT * FROM execution_lots WHERE status IN ("OPEN", "PARTIAL")'
    params = []
    
    if channel_id:
        query += ' AND channel_id = ?'
        params.append(str(channel_id))
    if broker:
        query += ' AND broker = ?'
        params.append(broker)
    if symbol:
        query += ' AND symbol = ?'
        params.append(symbol)
    
    query += ' ORDER BY order_filled_at ASC'
    cursor.execute(query, params)
    return cursor.fetchall()


def get_execution_lot_by_signal_lot(signal_lot_id: int, broker: str = None):
    """Get execution lot linked to a signal lot"""
    conn = get_connection()
    cursor = conn.cursor()
    
    if broker:
        cursor.execute(
            'SELECT * FROM execution_lots WHERE signal_lot_id = ? AND broker = ?',
            (signal_lot_id, broker)
        )
    else:
        cursor.execute(
            'SELECT * FROM execution_lots WHERE signal_lot_id = ?',
            (signal_lot_id,)
        )
    return cursor.fetchone()


def create_execution_closure(
    execution_lot_id: int,
    channel_id: str,
    broker: str,
    closed_qty: int,
    fill_price: float,
    filled_at,
    exit_source: str,
    signal_lot_closure_id: int = None,
    broker_order_id: str = None,
    signal_exit_price: float = None,
    order_submitted_at = None
):
    """Create an execution closure record with P&L calculation"""
    import hashlib
    from datetime import datetime
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM execution_lots WHERE id = ?', (execution_lot_id,))
    exec_lot = cursor.fetchone()
    
    if not exec_lot:
        print(f"[DATABASE] Execution lot {execution_lot_id} not found")
        return None
    
    if exec_lot['remaining_qty'] <= 0:
        print(f"[DATABASE] Execution lot {execution_lot_id} already fully closed")
        return None
    
    multiplier = 100 if exec_lot['asset_type'] == 'option' else 1
    cost_basis = exec_lot['fill_price'] * closed_qty * multiplier
    proceeds = fill_price * closed_qty * multiplier
    pnl = round(proceeds - cost_basis, 2)
    pnl_percent = round((pnl / cost_basis * 100), 4) if cost_basis > 0 else 0
    
    slippage_pct = None
    if signal_exit_price and signal_exit_price > 0:
        slippage_pct = round(((fill_price - signal_exit_price) / signal_exit_price) * 100, 4)
    
    filled_dt = filled_at if isinstance(filled_at, datetime) else datetime.fromisoformat(str(filled_at))
    opened_dt = exec_lot['order_filled_at']
    if isinstance(opened_dt, str):
        opened_dt = datetime.fromisoformat(opened_dt)
    holding_days = (filled_dt - opened_dt).total_seconds() / 86400
    
    latency_broker_ms = None
    if order_submitted_at:
        submitted_dt = order_submitted_at if isinstance(order_submitted_at, datetime) else datetime.fromisoformat(str(order_submitted_at))
        latency_broker_ms = int((filled_dt - submitted_dt).total_seconds() * 1000)
    
    closure_hash = hashlib.sha256(
        f"{execution_lot_id}:{broker}:{closed_qty}:{filled_at}".encode()
    ).hexdigest()[:32]
    
    try:
        cursor.execute('''
            INSERT INTO execution_closures (
                execution_lot_id, signal_lot_closure_id, channel_id, broker,
                broker_order_id, closed_qty, fill_price, signal_exit_price,
                slippage_pct, order_submitted_at, filled_at, latency_broker_ms,
                pnl, pnl_percent, holding_days, exit_source, closure_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            execution_lot_id, signal_lot_closure_id, str(channel_id), broker,
            broker_order_id, closed_qty, fill_price, signal_exit_price,
            slippage_pct, order_submitted_at, filled_at, latency_broker_ms,
            pnl, pnl_percent, holding_days, exit_source, closure_hash
        ))
        
        new_remaining = exec_lot['remaining_qty'] - closed_qty
        if new_remaining <= 0:
            cursor.execute('UPDATE execution_lots SET remaining_qty = 0, status = "CLOSED" WHERE id = ?', (execution_lot_id,))
        else:
            cursor.execute('UPDATE execution_lots SET remaining_qty = ?, status = "PARTIAL" WHERE id = ?', (new_remaining, execution_lot_id))
        
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        if 'UNIQUE constraint failed' in str(e):
            print(f"[DATABASE] Duplicate closure prevented: {closure_hash}")
            return None
        print(f"[DATABASE] Error creating execution closure: {e}")
        return None


def insert_execution_lot(
    channel_id: str, broker: str, symbol: str, asset_type: str,
    original_qty: int, remaining_qty: int, fill_price: float, order_filled_at,
    signal_lot_id: int = None, broker_order_id: str = None,
    strike: float = None, expiry: str = None, call_put: str = None,
    signal_price: float = None, slippage_pct: float = None,
    signal_detected_at = None, signal_parsed_at = None, order_submitted_at = None,
    latency_parse_ms: int = None, latency_broker_ms: int = None, latency_total_ms: int = None,
    analyst_entry_qty: int = None, sizing_mode: str = None, sizing_details: str = None
):
    """Insert an execution lot (entry fill) for Execution P&L tracking"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO execution_lots (
                signal_lot_id, channel_id, broker, broker_order_id,
                symbol, asset_type, strike, expiry, call_put,
                original_qty, remaining_qty, fill_price, signal_price, slippage_pct,
                signal_detected_at, signal_parsed_at, order_submitted_at, order_filled_at,
                latency_parse_ms, latency_broker_ms, latency_total_ms,
                analyst_entry_qty, sizing_mode, sizing_details, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
        ''', (
            signal_lot_id, str(channel_id), broker, broker_order_id,
            symbol, asset_type, strike, expiry, call_put,
            original_qty, remaining_qty, fill_price, signal_price, slippage_pct,
            signal_detected_at, signal_parsed_at, order_submitted_at, order_filled_at,
            latency_parse_ms, latency_broker_ms, latency_total_ms,
            analyst_entry_qty, sizing_mode, sizing_details
        ))
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        if 'UNIQUE constraint failed' in str(e):
            return None
        print(f"[DATABASE] Error inserting execution lot: {e}")
        return None


def find_matching_execution_lot(broker: str, symbol: str, asset_type: str,
                                  strike: float = None, expiry: str = None, call_put: str = None):
    """Find oldest open execution lot matching position criteria (FIFO)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
        SELECT * FROM execution_lots 
        WHERE broker = ? AND symbol = ? AND asset_type = ? 
        AND status IN ('OPEN', 'PARTIAL') AND remaining_qty > 0
    '''
    params = [broker, symbol, asset_type]
    
    if asset_type == 'option':
        if strike is not None:
            query += ' AND strike = ?'
            params.append(strike)
        if expiry:
            query += ' AND expiry = ?'
            params.append(expiry)
        if call_put:
            query += ' AND call_put = ?'
            params.append(call_put)
    
    query += ' ORDER BY order_filled_at ASC LIMIT 1'
    cursor.execute(query, params)
    return cursor.fetchone()


def insert_execution_closure(
    execution_lot_id: int, channel_id: str, broker: str,
    closed_qty: int, fill_price: float, filled_at,
    pnl: float, pnl_percent: float, exit_source: str,
    signal_lot_closure_id: int = None, broker_order_id: str = None,
    signal_exit_price: float = None, slippage_pct: float = None,
    order_submitted_at = None, latency_broker_ms: int = None,
    holding_days: float = None, closure_hash: str = None
):
    """Insert an execution closure record"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO execution_closures (
                execution_lot_id, signal_lot_closure_id, channel_id, broker,
                broker_order_id, closed_qty, fill_price, signal_exit_price,
                slippage_pct, order_submitted_at, filled_at, latency_broker_ms,
                pnl, pnl_percent, holding_days, exit_source, closure_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            execution_lot_id, signal_lot_closure_id, str(channel_id), broker,
            broker_order_id, closed_qty, fill_price, signal_exit_price,
            slippage_pct, order_submitted_at, filled_at, latency_broker_ms,
            pnl, pnl_percent, holding_days, exit_source, closure_hash
        ))
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        if 'UNIQUE constraint failed' in str(e):
            return None
        print(f"[DATABASE] Error inserting execution closure: {e}")
        return None


def update_execution_lot_remaining(lot_id: int, remaining_qty: int, status: str):
    """Update execution lot remaining quantity and status"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            'UPDATE execution_lots SET remaining_qty = ?, status = ? WHERE id = ?',
            (remaining_qty, status, lot_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"[DATABASE] Error updating execution lot: {e}")
        return False


def get_execution_pnl(channel_id: str = None, broker: str = None, days: int = None, limit: int = 100, user: str = None, exit_source: str = None):
    """Get execution-based P&L with optional filtering including channel names and author info"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
        SELECT 
            ec.id, ec.execution_lot_id, ec.channel_id, ec.broker,
            ec.closed_qty, ec.fill_price as exit_fill_price, ec.signal_exit_price,
            ec.slippage_pct as exit_slippage_pct, ec.filled_at as exit_filled_at,
            ec.pnl, ec.pnl_percent, ec.holding_days, ec.exit_source,
            el.symbol, el.asset_type, el.strike, el.expiry, el.call_put,
            el.fill_price as entry_fill_price, el.signal_price as entry_signal_price,
            el.slippage_pct as entry_slippage_pct, el.order_filled_at as entry_filled_at,
            el.signal_detected_at, el.latency_total_ms,
            el.analyst_entry_qty, el.sizing_mode,
            c.name as channel_name,
            COALESCE(sl.author_name, sig.author_name) as author_name,
            el.signal_lot_id
        FROM execution_closures ec
        JOIN execution_lots el ON ec.execution_lot_id = el.id
        LEFT JOIN channels c ON ec.channel_id = c.discord_channel_id
        LEFT JOIN signal_lots sl ON el.signal_lot_id = sl.id
        LEFT JOIN signals sig ON sl.signal_id = sig.id
        WHERE 1=1
    '''
    params = []
    
    if channel_id:
        query += ' AND ec.channel_id = ?'
        params.append(str(channel_id))
    if broker:
        query += ' AND UPPER(ec.broker) LIKE UPPER(?)'
        params.append(f'%{broker}%')
    if days:
        query += ' AND ec.filled_at >= datetime("now", ?)'
        params.append(f'-{days} days')
    if user:
        query += ' AND COALESCE(sl.author_name, sig.author_name) LIKE ?'
        params.append(f'%{user}%')
    if exit_source:
        query += ' AND ec.exit_source = ?'
        params.append(exit_source)
    
    query += ' ORDER BY ec.filled_at DESC LIMIT ?'
    params.append(limit)
    
    cursor.execute(query, params)
    return cursor.fetchall()


def get_execution_pnl_users():
    """Get unique list of users/authors from execution P&L data for filtering"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT DISTINCT COALESCE(sl.author_name, sig.author_name) as author_name
        FROM execution_closures ec
        JOIN execution_lots el ON ec.execution_lot_id = el.id
        LEFT JOIN signal_lots sl ON el.signal_lot_id = sl.id
        LEFT JOIN signals sig ON sl.signal_id = sig.id
        WHERE COALESCE(sl.author_name, sig.author_name) IS NOT NULL 
              AND COALESCE(sl.author_name, sig.author_name) != ''
        ORDER BY author_name
    ''')
    
    return [row[0] for row in cursor.fetchall()]


def get_execution_pnl_channels():
    """Get unique list of channels from execution P&L data for filtering"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT DISTINCT ec.channel_id, c.name
        FROM execution_closures ec
        LEFT JOIN channels c ON ec.channel_id = c.discord_channel_id
        ORDER BY c.name
    ''')
    
    return [{'id': row[0], 'name': row[1] or f"Channel {row[0][:8]}..."} for row in cursor.fetchall()]


def get_execution_pnl_brokers():
    """Get unique list of brokers from execution P&L data for filtering"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT DISTINCT broker FROM execution_closures WHERE broker IS NOT NULL ORDER BY broker
    ''')
    
    return [row[0] for row in cursor.fetchall()]


def get_execution_leaderboard(days: int = None):
    """Get channel leaderboard based on actual execution P&L"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
        SELECT 
            ec.channel_id,
            c.name as channel_name,
            COUNT(*) as total_trades,
            COUNT(CASE WHEN ec.pnl > 0 THEN 1 END) as win_count,
            COUNT(CASE WHEN ec.pnl <= 0 THEN 1 END) as loss_count,
            ROUND(COUNT(CASE WHEN ec.pnl > 0 THEN 1 END) * 100.0 / COUNT(*), 2) as win_rate,
            ROUND(SUM(ec.pnl), 2) as total_pnl,
            ROUND(AVG(ec.pnl), 2) as avg_pnl,
            ROUND(AVG(ec.pnl_percent), 2) as avg_pnl_percent,
            ROUND(AVG(el.latency_total_ms), 0) as avg_latency_ms,
            ROUND(AVG(el.slippage_pct), 4) as avg_entry_slippage,
            ROUND(AVG(ec.slippage_pct), 4) as avg_exit_slippage
        FROM execution_closures ec
        JOIN execution_lots el ON ec.execution_lot_id = el.id
        LEFT JOIN channels c ON ec.channel_id = c.discord_channel_id
        WHERE 1=1
    '''
    params = []
    
    if days:
        query += ' AND ec.filled_at >= datetime("now", ?)'
        params.append(f'-{days} days')
    
    query += '''
        GROUP BY ec.channel_id
        ORDER BY total_pnl DESC
    '''
    
    cursor.execute(query, params)
    return cursor.fetchall()


def get_signal_execution_summary(channel_id: str = None, user: str = None, days: int = None, limit: int = 100):
    """Get signal-level aggregation with per-broker execution breakdown.
    Returns one row per signal with aggregated P&L across all broker executions."""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
        SELECT 
            sl.id as signal_lot_id,
            sl.symbol,
            sl.asset_type,
            sl.strike,
            sl.expiry,
            sl.call_put,
            COALESCE(sl.original_qty, 0) as signal_qty,
            sl.signal_price,
            sl.author_name,
            sl.channel_id,
            c.name as channel_name,
            sl.opened_at,
            sl.status as signal_status,
            COALESCE(COUNT(DISTINCT el.id), 0) as broker_count,
            GROUP_CONCAT(DISTINCT el.broker) as brokers_used,
            COALESCE(SUM(ec.closed_qty), 0) as total_closed_qty,
            COALESCE(ROUND(SUM(ec.pnl), 2), 0) as total_pnl,
            COALESCE(ROUND(AVG(ec.pnl_percent), 2), 0) as avg_pnl_percent,
            COALESCE(ROUND(AVG(el.slippage_pct), 4), 0) as avg_entry_slippage,
            COALESCE(ROUND(AVG(ec.slippage_pct), 4), 0) as avg_exit_slippage,
            COALESCE(ROUND(AVG(el.latency_total_ms), 0), 0) as avg_latency_ms,
            MAX(ec.filled_at) as last_exit_at
        FROM signal_lots sl
        LEFT JOIN execution_lots el ON el.signal_lot_id = sl.id
        LEFT JOIN execution_closures ec ON ec.execution_lot_id = el.id
        LEFT JOIN channels c ON sl.channel_id = c.discord_channel_id
        WHERE 1=1
    '''
    params = []
    
    if channel_id:
        query += ' AND sl.channel_id = ?'
        params.append(str(channel_id))
    if user:
        query += ' AND sl.author_name LIKE ?'
        params.append(f'%{user}%')
    if days:
        query += ' AND sl.opened_at >= datetime("now", ?)'
        params.append(f'-{days} days')
    
    query += '''
        GROUP BY sl.id
        ORDER BY sl.opened_at DESC
        LIMIT ?
    '''
    params.append(limit)
    
    cursor.execute(query, params)
    return cursor.fetchall()


def get_signal_execution_details(signal_lot_id: int):
    """Get all broker-level execution details for a specific signal lot.
    Used for master-detail expansion."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            el.id as execution_lot_id,
            el.broker,
            el.original_qty,
            el.remaining_qty,
            el.fill_price as entry_fill_price,
            el.signal_price as entry_signal_price,
            el.slippage_pct as entry_slippage,
            el.latency_total_ms,
            el.order_filled_at as entry_filled_at,
            el.status as lot_status,
            ec.closed_qty,
            ec.fill_price as exit_fill_price,
            ec.signal_exit_price,
            ec.slippage_pct as exit_slippage,
            ec.pnl,
            ec.pnl_percent,
            ec.exit_source,
            ec.filled_at as exit_filled_at
        FROM execution_lots el
        LEFT JOIN execution_closures ec ON ec.execution_lot_id = el.id
        WHERE el.signal_lot_id = ?
        ORDER BY el.broker, ec.filled_at
    ''', (signal_lot_id,))
    
    return cursor.fetchall()


# ============================================
# PENDING ORDER METADATA FUNCTIONS
# Bridge between order placement and BrokerSyncService
# ============================================

def save_pending_order_metadata(
    broker: str, channel_id: str, symbol: str, asset_type: str, action: str, quantity: int,
    broker_order_id: str = None, client_order_id: str = None, message_id: str = None,
    signal_lot_id: int = None, signal_price: float = None, analyst_qty: int = None,
    sizing_mode: str = None, sizing_details: str = None,
    signal_detected_at = None, signal_parsed_at = None
):
    """Save signal context when order is placed for later hydration by BrokerSyncService"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO pending_order_metadata (
                broker, broker_order_id, client_order_id, channel_id, message_id,
                signal_lot_id, symbol, asset_type, action, quantity, signal_price,
                analyst_qty, sizing_mode, sizing_details,
                signal_detected_at, signal_parsed_at, order_submitted_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 'PENDING')
        ''', (
            broker, broker_order_id, client_order_id, str(channel_id), message_id,
            signal_lot_id, symbol, asset_type, action, quantity, signal_price,
            analyst_qty, sizing_mode, sizing_details,
            signal_detected_at, signal_parsed_at
        ))
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        if 'UNIQUE constraint failed' not in str(e):
            print(f"[DATABASE] Error saving pending order metadata: {e}")
        return None


def get_pending_order_metadata(broker: str, broker_order_id: str = None, client_order_id: str = None):
    """Lookup pending order metadata by broker_order_id or client_order_id"""
    conn = get_connection()
    cursor = conn.cursor()
    
    if broker_order_id:
        cursor.execute('''
            SELECT * FROM pending_order_metadata 
            WHERE broker = ? AND broker_order_id = ? AND status = 'PENDING'
        ''', (broker, broker_order_id))
    elif client_order_id:
        cursor.execute('''
            SELECT * FROM pending_order_metadata 
            WHERE broker = ? AND client_order_id = ? AND status = 'PENDING'
        ''', (broker, client_order_id))
    else:
        return None
    
    return cursor.fetchone()


def update_pending_order_status(broker: str, broker_order_id: str, status: str, filled_order_id: str = None):
    """Mark pending order as filled/cancelled/expired"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE pending_order_metadata 
            SET status = ? 
            WHERE broker = ? AND broker_order_id = ?
        ''', (status, broker, broker_order_id))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"[DATABASE] Error updating pending order status: {e}")
        return False


def map_risk_trigger_to_exit_source(risk_trigger: str, tier: int = None) -> str:
    """
    Map risk_trigger from trades table to exit_source enum for execution_closures.
    
    Valid exit_source values: 'SIGNAL', 'PT1', 'PT2', 'PT3', 'PT4', 'STOP_LOSS', 'TRAILING', 'MANUAL', 'RISK'
    
    Args:
        risk_trigger: Value from trades.risk_trigger (trailing_stop, profit_target, stop_loss, etc.)
        tier: Optional tier number for profit target exits (1-4)
    
    Returns:
        Valid exit_source string for execution_closures table
    """
    if not risk_trigger:
        return 'SIGNAL'
    
    trigger_lower = risk_trigger.lower()
    
    if 'trailing' in trigger_lower:
        return 'TRAILING'
    elif 'stop' in trigger_lower and 'loss' in trigger_lower:
        return 'STOP_LOSS'
    elif 'profit' in trigger_lower or 'target' in trigger_lower or trigger_lower.startswith('pt'):
        if tier:
            return f'PT{tier}' if tier <= 4 else 'PT4'
        if '1' in trigger_lower:
            return 'PT1'
        elif '2' in trigger_lower:
            return 'PT2'
        elif '3' in trigger_lower:
            return 'PT3'
        elif '4' in trigger_lower:
            return 'PT4'
        return 'PT1'
    elif trigger_lower in ('manual', 'user'):
        return 'MANUAL'
    elif trigger_lower in ('risk', 'risk_management'):
        return 'RISK'
    
    return 'SIGNAL'


def record_execution_closure_atomic(
    broker: str, symbol: str, asset_type: str, closed_qty: int, fill_price: float, filled_at,
    exit_source: str = 'SIGNAL', strike: float = None, expiry: str = None, call_put: str = None,
    broker_order_id: str = None, signal_exit_price: float = None,
    order_submitted_at = None, channel_id: str = None
):
    """
    Atomically find matching lot, insert closure, and update remaining quantity.
    Uses BEGIN IMMEDIATE for transaction safety with concurrent fills.
    Returns (closure_id, pnl) or (None, None) if failed.
    """
    import hashlib
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # BEGIN IMMEDIATE for exclusive write lock
        cursor.execute('BEGIN IMMEDIATE')
        
        # Find matching execution lot (FIFO)
        query = '''
            SELECT * FROM execution_lots 
            WHERE broker = ? AND symbol = ? AND asset_type = ? 
            AND status IN ('OPEN', 'PARTIAL') AND remaining_qty > 0
        '''
        params = [broker, symbol, asset_type]
        
        if asset_type == 'option':
            if strike is not None:
                query += ' AND strike = ?'
                params.append(strike)
            if expiry:
                query += ' AND expiry = ?'
                params.append(expiry)
            if call_put:
                query += ' AND call_put = ?'
                params.append(call_put)
        
        query += ' ORDER BY order_filled_at ASC LIMIT 1'
        cursor.execute(query, params)
        exec_lot = cursor.fetchone()
        
        if not exec_lot:
            cursor.execute('ROLLBACK')
            return None, None
        
        # Calculate P&L
        entry_price = exec_lot['fill_price']
        multiplier = 100 if asset_type == 'option' else 1
        pnl = (fill_price - entry_price) * closed_qty * multiplier
        pnl_percent = ((fill_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        
        # Calculate holding days
        holding_days = None
        if exec_lot['order_filled_at']:
            try:
                from datetime import datetime
                if isinstance(filled_at, str):
                    exit_dt = datetime.fromisoformat(filled_at.replace('Z', '+00:00'))
                else:
                    exit_dt = filled_at
                entry_dt = datetime.fromisoformat(str(exec_lot['order_filled_at']).replace('Z', '+00:00'))
                holding_days = (exit_dt - entry_dt).total_seconds() / 86400
            except:
                pass
        
        # Calculate slippage
        slippage_pct = None
        if signal_exit_price and signal_exit_price > 0:
            slippage_pct = (fill_price - signal_exit_price) / signal_exit_price * 100
        
        # Generate closure hash for deduplication
        closure_hash = hashlib.sha256(
            f"{exec_lot['id']}:{broker}:{closed_qty}:{filled_at}".encode()
        ).hexdigest()[:32]
        
        # Use provided channel_id or fallback to lot's channel_id
        final_channel_id = channel_id or exec_lot['channel_id']
        
        # Insert closure
        cursor.execute('''
            INSERT INTO execution_closures (
                execution_lot_id, channel_id, broker, broker_order_id,
                closed_qty, fill_price, signal_exit_price, slippage_pct,
                order_submitted_at, filled_at, pnl, pnl_percent, holding_days,
                exit_source, closure_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            exec_lot['id'], final_channel_id, broker, broker_order_id,
            closed_qty, fill_price, signal_exit_price, slippage_pct,
            order_submitted_at, filled_at, pnl, pnl_percent, holding_days,
            exit_source, closure_hash
        ))
        
        # Update lot remaining quantity
        new_remaining = exec_lot['remaining_qty'] - closed_qty
        if new_remaining <= 0:
            cursor.execute('UPDATE execution_lots SET remaining_qty = 0, status = "CLOSED" WHERE id = ?', (exec_lot['id'],))
        else:
            cursor.execute('UPDATE execution_lots SET remaining_qty = ?, status = "PARTIAL" WHERE id = ?', (new_remaining, exec_lot['id']))
        
        cursor.execute('COMMIT')
        return cursor.lastrowid, pnl
        
    except Exception as e:
        cursor.execute('ROLLBACK')
        if 'UNIQUE constraint failed' in str(e):
            return None, None  # Duplicate closure, already processed
        print(f"[DATABASE] Error in atomic closure: {e}")
        return None, None


def get_performance_metrics(channel_id: int = None, period_start=None, period_end=None):
    """Get aggregated performance metrics"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
        SELECT 
            l.symbol,
            l.asset_type,
            l.strike,
            l.expiry,
            l.call_put,
            COUNT(DISTINCT c.id) as total_trades,
            COUNT(DISTINCT CASE WHEN c.pnl > 0 THEN c.id END) as wins,
            COUNT(DISTINCT CASE WHEN c.pnl <= 0 THEN c.id END) as losses,
            SUM(c.pnl) as total_pnl,
            AVG(c.pnl) as avg_pnl,
            AVG(c.pnl_percent) as avg_pnl_percent,
            AVG(c.holding_days) as avg_holding_days
        FROM signal_lots l
        LEFT JOIN lot_closures c ON l.id = c.lot_id
        WHERE 1=1
    '''
    
    params = []
    if channel_id:
        query += ' AND l.channel_id = ?'
        params.append(channel_id)
    
    if period_start:
        query += ' AND c.closed_at >= ?'
        params.append(period_start)
    
    if period_end:
        query += ' AND c.closed_at <= ?'
        params.append(period_end)
    
    query += ' GROUP BY l.symbol, l.asset_type, l.strike, l.expiry, l.call_put'
    query += ' ORDER BY total_pnl DESC'
    
    cursor.execute(query, params)
    return cursor.fetchall()


# Signal management functions
def add_signal(discord_channel_id: str, message_id: str, signal_type: str, symbol: str, quantity: int, price: float = None, asset_type: str = 'stock', author_name: str = None, strike: float = None, expiry: str = None, call_put: str = None, market: str = 'US'):
    """Add a new signal to the database with author attribution and option details"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get channel internal ID - check both discord_channel_id and telegram_chat_id
    cursor.execute('SELECT id FROM channels WHERE discord_channel_id = ? OR telegram_chat_id = ?', (discord_channel_id, discord_channel_id))
    channel = cursor.fetchone()
    channel_id = channel['id'] if channel else None
    
    try:
        cursor.execute('''
            INSERT INTO signals (
                channel_id, message_id, direction, asset_type, symbol,
                quantity, price, strike, expiry, call_put, author_name, received_at, executed, market
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 0, ?)
        ''', (channel_id, message_id, signal_type, asset_type, symbol, quantity, price, strike, expiry, call_put, author_name, market))
        
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None  # Signal already exists


def update_signal_execution_status(message_id: str, status: str, reason: str = None):
    """Update signal execution status and reason after order attempt
    
    Args:
        message_id: Discord message ID of the signal
        status: EXECUTED, FAILED, SKIPPED, PENDING
        reason: Detailed reason for the status (e.g., "Price slippage 15%", "Broker disconnected")
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE signals 
            SET execution_status = ?, execution_reason = ?, executed = ?
            WHERE message_id = ?
        ''', (status, reason, 1 if status == 'EXECUTED' else 0, str(message_id)))
        
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"[DATABASE] Error updating signal execution status: {e}")
        return False


def get_channel_leaderboard(time_period='all', start_date=None, end_date=None, market='US'):
    """
    Get channel performance leaderboard with TQS scoring.
    
    Args:
        time_period: 'today', '7d', '30d', 'year', 'all', or 'custom'
        start_date: For custom period (YYYY-MM-DD)
        end_date: For custom period (YYYY-MM-DD)
        market: 'US' or 'INDIA' for market-specific filtering
    
    Returns:
        List of channels sorted by TQS score with:
        - channel_id, channel_name
        - total_trades, total_closed
        - win_count, loss_count, win_rate
        - total_pnl, avg_pnl, gross_profit, gross_loss
        - best_trade, worst_trade
        - score (TQS)
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get date bounds for filtering by close_date
    date_start, date_end = get_date_filter_bounds(time_period, start_date, end_date)
    
    # Build date filter SQL with bound parameters
    date_filter = ""
    params = []
    if date_start and date_end:
        date_filter = "AND lc.closed_at >= ? AND lc.closed_at <= ?"
        params.extend([date_start, date_end])
    
    # Market filter using bound parameters (safe from SQL injection)
    # Filter via signals table which has the market column
    market_filter = ""
    if market and market in ('US', 'INDIA'):
        market_filter = "AND COALESCE(s.market, 'US') = ?"
        params.append(market)
    
    query = f'''
        SELECT 
            c.id as channel_id,
            c.name as channel_name,
            c.discord_channel_id,
            
            -- Total signals (BTO + STC)
            COUNT(DISTINCT s.id) as total_signals,
            
            -- Total closed positions (from lot_closures)
            COUNT(DISTINCT lc.id) as total_closed,
            
            -- Win/Loss counts (based on PNL)
            SUM(CASE WHEN lc.pnl > 0 THEN 1 ELSE 0 END) as win_count,
            SUM(CASE WHEN lc.pnl <= 0 THEN 1 ELSE 0 END) as loss_count,
            
            -- Win rate (%)
            CASE 
                WHEN COUNT(DISTINCT lc.id) > 0 
                THEN ROUND(SUM(CASE WHEN lc.pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(DISTINCT lc.id), 2)
                ELSE 0 
            END as win_rate,
            
            -- PNL metrics
            COALESCE(SUM(lc.pnl), 0) as total_pnl,
            CASE 
                WHEN COUNT(DISTINCT lc.id) > 0 
                THEN ROUND(SUM(lc.pnl) / COUNT(DISTINCT lc.id), 2)
                ELSE 0 
            END as avg_pnl,
            
            -- Cost basis: US options multiply by 100, India F&O uses 1× (lot sizing in qty)
            COALESCE(SUM(sl.open_price * lc.closed_qty * 
                CASE 
                    WHEN sl.asset_type = 'option' AND COALESCE(s.market, 'US') = 'US' THEN 100 
                    ELSE 1 
                END
            ), 0) as total_cost_basis,
            
            -- Gross profit/loss for TQS calculation
            COALESCE(SUM(CASE WHEN lc.pnl > 0 THEN lc.pnl ELSE 0 END), 0) as gross_profit,
            COALESCE(SUM(CASE WHEN lc.pnl < 0 THEN lc.pnl ELSE 0 END), 0) as gross_loss,
            
            -- Best and worst trades
            MAX(lc.pnl) as best_trade,
            MIN(lc.pnl) as worst_trade,
            
            -- Average holding days
            ROUND(AVG(lc.holding_days), 1) as avg_holding_days
            
        FROM channels c
        LEFT JOIN signals s ON s.channel_id = c.id
        LEFT JOIN signal_lots sl ON sl.signal_id = s.id
        LEFT JOIN lot_closures lc ON lc.lot_id = sl.id
        WHERE c.is_active = 1 {date_filter} {market_filter}
        GROUP BY c.id, c.name, c.discord_channel_id
        HAVING COUNT(DISTINCT lc.id) > 0
    '''
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    channels = []
    for row in rows:
        # Calculate weighted average % return based on cost basis
        total_pnl = float(row['total_pnl'] or 0)
        total_cost_basis = float(row['total_cost_basis'] or 0)
        if total_cost_basis > 0:
            weighted_avg_pnl_percent = (total_pnl / total_cost_basis) * 100
        else:
            weighted_avg_pnl_percent = 0
        
        channels.append({
            'channel_id': row['channel_id'],
            'channel_name': row['channel_name'],
            'discord_channel_id': row['discord_channel_id'],
            'total_signals': row['total_signals'] or 0,
            'total_closed': row['total_closed'] or 0,
            'win_count': row['win_count'] or 0,
            'loss_count': row['loss_count'] or 0,
            'win_rate': float(row['win_rate'] or 0),
            'total_pnl': round(total_pnl, 2),
            'avg_pnl': float(row['avg_pnl'] or 0),
            'avg_pnl_percent': round(weighted_avg_pnl_percent, 1),
            'gross_profit': round(float(row['gross_profit'] or 0), 2),
            'gross_loss': round(float(row['gross_loss'] or 0), 2),
            'best_trade': round(float(row['best_trade'] or 0), 2),
            'worst_trade': round(float(row['worst_trade'] or 0), 2),
            'avg_holding_days': float(row['avg_holding_days'] or 0)
        })
    
    # Calculate min/max total_pnl for TQS normalization (handles negative values)
    if channels:
        max_total_pnl = max((ch['total_pnl'] for ch in channels), default=0)
        min_total_pnl = min((ch['total_pnl'] for ch in channels), default=0)
    else:
        max_total_pnl = 1
        min_total_pnl = 0
    
    # Calculate TQS score for each channel
    for ch in channels:
        # Calculate profit factor for display (not capped)
        if ch['gross_loss'] == 0:
            ch['profit_factor'] = 2.0 if ch['gross_profit'] > 0 else 0.0
        else:
            ch['profit_factor'] = round(min(ch['gross_profit'] / abs(ch['gross_loss']), 10.0), 2)
        
        tqs_stats = {
            'total_pnl': ch['total_pnl'],
            'gross_profit': ch['gross_profit'],
            'gross_loss': ch['gross_loss'],
            'win_trades': ch['win_count'],
            'loss_trades': ch['loss_count'],
            'avg_pct_pnl': ch['avg_pnl_percent']
        }
        ch['score'] = calculate_trader_quality_score(tqs_stats, max_total_pnl, min_total_pnl)
    
    # Sort by TQS score (primary), then total_pnl (secondary)
    channels.sort(key=lambda c: (-c['score'], -c['total_pnl']))
    
    return channels

def get_channel_user_performance(channel_id, time_period='all'):
    """
    Get user performance for a specific channel with leaderboard-style metrics
    
    Args:
        channel_id: Internal channel ID
        time_period: 'all', 'week', 'month', 'year'
    
    Returns:
        List of users with metrics: wins, losses, win_rate, total_pnl, avg_pnl, avg_pnl_percent
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Build date filter
    date_filter = ""
    if time_period == 'week':
        date_filter = "AND lc.closed_at >= datetime('now', '-7 days')"
    elif time_period == 'month':
        date_filter = "AND lc.closed_at >= datetime('now', '-30 days')"
    elif time_period == 'year':
        date_filter = "AND lc.closed_at >= datetime('now', '-365 days')"
    
    query = f'''
        SELECT 
            s.author_name,
            
            -- Total signals from this user in this channel
            COUNT(DISTINCT s.id) as total_signals,
            
            -- Closed trades (lot_closures)
            COUNT(DISTINCT lc.id) as total_closed,
            
            -- Win/Loss counts
            SUM(CASE WHEN lc.pnl > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN lc.pnl <= 0 THEN 1 ELSE 0 END) as losses,
            
            -- Win rate (%)
            CASE 
                WHEN COUNT(DISTINCT lc.id) > 0 
                THEN ROUND(SUM(CASE WHEN lc.pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(DISTINCT lc.id), 2)
                ELSE 0 
            END as win_rate,
            
            -- PNL metrics
            COALESCE(SUM(lc.pnl), 0) as total_pnl,
            CASE 
                WHEN COUNT(DISTINCT lc.id) > 0 
                THEN ROUND(SUM(lc.pnl) / COUNT(DISTINCT lc.id), 2)
                ELSE 0 
            END as avg_pnl,
            CASE 
                WHEN COUNT(DISTINCT lc.id) > 0 
                THEN ROUND(AVG(lc.pnl_percent), 1)
                ELSE 0 
            END as avg_pnl_percent
            
        FROM signals s
        LEFT JOIN signal_lots sl ON sl.signal_id = s.id
        LEFT JOIN lot_closures lc ON lc.lot_id = sl.id
        WHERE s.channel_id = ? {date_filter}
        GROUP BY s.author_name
        ORDER BY total_pnl DESC, win_rate DESC
    '''
    
    cursor.execute(query, (channel_id,))
    rows = cursor.fetchall()
    
    users = []
    for row in rows:
        users.append({
            'name': row['author_name'] or 'Unknown',
            'author_name': row['author_name'] or 'Unknown',
            'total_signals': row['total_signals'] or 0,
            'total_closed': row['total_closed'] or 0,
            'wins': row['wins'] or 0,
            'losses': row['losses'] or 0,
            'win_rate': float(row['win_rate'] or 0),
            'total_pnl': round(float(row['total_pnl'] or 0), 2),
            'avg_pnl': round(float(row['avg_pnl'] or 0), 2),
            'avg_pnl_percent': float(row['avg_pnl_percent'] or 0)
        })
    
    return users


def get_signal_history(channel_id=None, period='all', limit=100):
    """
    Get signal history with PNL data
    
    Args:
        channel_id: Filter by specific channel (None = all channels)
        period: 'weekly', 'monthly', 'yearly', 'all'
        limit: Maximum number of signals to return
    
    Returns:
        List of signals with PNL metrics
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Build time filter based on period
    time_filter = ""
    if period == 'weekly':
        time_filter = "AND s.received_at >= datetime('now', '-7 days')"
    elif period == 'monthly':
        time_filter = "AND s.received_at >= datetime('now', '-30 days')"
    elif period == 'yearly':
        time_filter = "AND s.received_at >= datetime('now', '-365 days')"
    
    # Build channel filter
    channel_filter = ""
    params = []
    if channel_id:
        channel_filter = "AND s.channel_id = ?"
        params.append(channel_id)
    
    # Query to get signals with aggregated PNL data
    query = f'''
        SELECT 
            s.id,
            s.direction,
            s.symbol,
            s.asset_type,
            s.quantity,
            s.price,
            s.received_at,
            s.executed,
            s.author_name,
            s.message_id,
            s.execution_status,
            s.execution_reason,
            c.name as channel_name,
            c.id as channel_id,
            
            -- For BTO signals, get total PNL from all closures
            COALESCE(
                (SELECT SUM(lc.pnl) 
                 FROM signal_lots sl
                 LEFT JOIN lot_closures lc ON lc.lot_id = sl.id
                 WHERE sl.signal_id = s.id), 
                0
            ) as total_pnl,
            
            -- For BTO signals, calculate avg PNL percentage
            COALESCE(
                (SELECT AVG(lc.pnl_percent) 
                 FROM signal_lots sl
                 LEFT JOIN lot_closures lc ON lc.lot_id = sl.id
                 WHERE sl.signal_id = s.id AND lc.id IS NOT NULL), 
                0
            ) as pnl_percent,
            
            -- Get total closed quantity
            COALESCE(
                (SELECT SUM(lc.closed_qty) 
                 FROM signal_lots sl
                 LEFT JOIN lot_closures lc ON lc.lot_id = sl.id
                 WHERE sl.signal_id = s.id), 
                0
            ) as closed_qty,
            
            -- Get remaining open quantity
            COALESCE(
                (SELECT SUM(sl.remaining_qty) 
                 FROM signal_lots sl
                 WHERE sl.signal_id = s.id AND sl.status != 'CLOSED'), 
                0
            ) as remaining_qty,
            
            -- For STC signals, get the closure info
            COALESCE(
                (SELECT SUM(lc.pnl)
                 FROM lot_closures lc
                 WHERE lc.signal_id = s.id),
                0
            ) as stc_pnl,
            
            COALESCE(
                (SELECT AVG(lc.pnl_percent)
                 FROM lot_closures lc
                 WHERE lc.signal_id = s.id),
                0
            ) as stc_pnl_percent
            
        FROM signals s
        LEFT JOIN channels c ON c.id = s.channel_id
        WHERE 1=1 {time_filter} {channel_filter}
        ORDER BY s.received_at DESC
        LIMIT ?
    '''
    
    params.append(limit)
    cursor.execute(query, params)
    
    signals = []
    for row in cursor.fetchall():
        signal = dict(row)
        
        # Determine which PNL to use based on direction
        if signal['direction'] == 'BTO':
            signal['final_pnl'] = signal['total_pnl']
            signal['final_pnl_percent'] = signal['pnl_percent']
            signal['status'] = 'OPEN' if signal['remaining_qty'] > 0 else 'CLOSED'
        else:  # STC
            signal['final_pnl'] = signal['stc_pnl']
            signal['final_pnl_percent'] = signal['stc_pnl_percent']
            signal['status'] = 'CLOSED'
        
        signals.append(signal)
    
    return signals


def get_gui_exec_channel_id():
    """Get the internal ID of the GUI_EXEC channel for options page tracking"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM channels WHERE discord_channel_id = 'GUI_EXEC'")
    row = cursor.fetchone()
    return row['id'] if row else None


def get_user_performance(user_id: int, period: str = 'all', broker_filter: str = None) -> Dict[str, Any]:
    """
    Get trading performance for a specific user (logged-in web user) by period.
    
    Args:
        user_id: The app_users.id of the logged-in user
        period: 'today', '7d' (week), '30d' (month), 'year', 'all'
        broker_filter: Optional broker filter ('Webull', 'ALPACA_PAPER', etc.)
    
    Returns:
        Dict with performance metrics including:
        - total_trades, wins, losses, win_rate
        - total_pnl, gross_profit, gross_loss
        - avg_pnl, avg_pnl_percent, best_trade, worst_trade
        - daily_breakdown for charts
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Build date filter
    start_date, end_date = get_date_filter_bounds(period)
    
    # Build params in order they appear in WHERE clause: user_filter, date_filter, broker_clause
    params = [user_id]  # user_filter comes first in WHERE clause
    
    date_filter = ""
    if start_date and end_date:
        date_filter = "AND lc.closed_at BETWEEN ? AND ?"
        params.extend([start_date, end_date])
    
    # Broker filter with case-insensitive matching
    broker_clause = ""
    if broker_filter:
        broker_clause = "AND LOWER(t.broker) = LOWER(?)"
        params.append(broker_filter)
    
    # For now, show ALL data (user_id NULL or matching) since existing trades don't have user_id
    # This allows showing historical data while new trades will be properly attributed
    user_filter = "(lc.user_id IS NULL OR lc.user_id = ?)"
    
    # Main performance query - join via signal_lots to get broker from trades
    # Join path: lot_closures -> signal_lots (via lot_id) -> trades (via signal_id)
    query = f'''
        SELECT 
            COUNT(DISTINCT lc.id) as total_trades,
            SUM(CASE WHEN lc.pnl > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN lc.pnl <= 0 THEN 1 ELSE 0 END) as losses,
            COALESCE(SUM(lc.pnl), 0) as total_pnl,
            COALESCE(SUM(CASE WHEN lc.pnl > 0 THEN lc.pnl ELSE 0 END), 0) as gross_profit,
            COALESCE(SUM(CASE WHEN lc.pnl < 0 THEN lc.pnl ELSE 0 END), 0) as gross_loss,
            COALESCE(AVG(lc.pnl), 0) as avg_pnl,
            COALESCE(AVG(lc.pnl_percent), 0) as avg_pnl_percent,
            COALESCE(MAX(lc.pnl), 0) as best_trade,
            COALESCE(MIN(lc.pnl), 0) as worst_trade,
            COALESCE(AVG(lc.holding_days), 0) as avg_hold_days
        FROM lot_closures lc
        LEFT JOIN signal_lots sl ON lc.lot_id = sl.id
        LEFT JOIN trades t ON sl.signal_id = t.id
        WHERE {user_filter} {date_filter} {broker_clause}
    '''
    
    cursor.execute(query, tuple(params))
    row = cursor.fetchone()
    
    total_trades = row['total_trades'] or 0
    wins = row['wins'] or 0
    losses = row['losses'] or 0
    
    result = {
        'total_trades': total_trades,
        'wins': wins,
        'losses': losses,
        'win_rate': round((wins / total_trades * 100) if total_trades > 0 else 0, 1),
        'total_pnl': round(float(row['total_pnl'] or 0), 2),
        'gross_profit': round(float(row['gross_profit'] or 0), 2),
        'gross_loss': round(float(row['gross_loss'] or 0), 2),
        'avg_pnl': round(float(row['avg_pnl'] or 0), 2),
        'avg_pnl_percent': round(float(row['avg_pnl_percent'] or 0), 1),
        'best_trade': round(float(row['best_trade'] or 0), 2),
        'worst_trade': round(float(row['worst_trade'] or 0), 2),
        'avg_hold_days': round(float(row['avg_hold_days'] or 0), 1),
        'profit_factor': 0.0
    }
    
    # Calculate profit factor
    if result['gross_loss'] != 0:
        result['profit_factor'] = round(abs(result['gross_profit'] / result['gross_loss']), 2)
    elif result['gross_profit'] > 0:
        result['profit_factor'] = 10.0  # Cap at 10 if no losses
    
    return result


def get_user_daily_pnl(user_id: int, days: int = 30, broker_filter: str = None) -> List[Dict]:
    """
    Get daily PNL breakdown for a user for charting.
    
    Args:
        user_id: The app_users.id
        days: Number of days to look back
        broker_filter: Optional broker filter
    
    Returns:
        List of daily entries with date, pnl, cumulative_pnl, trades
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Build params in order they appear in WHERE clause: user_filter first, then broker_clause
    params = [user_id]  # user_filter comes first
    
    broker_clause = ""
    if broker_filter:
        broker_clause = "AND LOWER(t.broker) = LOWER(?)"
        params.append(broker_filter)
    
    # Join path: lot_closures -> signal_lots (via lot_id) -> trades (via signal_id)
    query = f'''
        SELECT 
            DATE(lc.closed_at) as date,
            SUM(lc.pnl) as daily_pnl,
            COUNT(*) as trades,
            SUM(CASE WHEN lc.pnl > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN lc.pnl <= 0 THEN 1 ELSE 0 END) as losses
        FROM lot_closures lc
        LEFT JOIN signal_lots sl ON lc.lot_id = sl.id
        LEFT JOIN trades t ON sl.signal_id = t.id
        WHERE (lc.user_id IS NULL OR lc.user_id = ?) 
        AND lc.closed_at >= datetime('now', '-{days} days')
        {broker_clause}
        GROUP BY DATE(lc.closed_at)
        ORDER BY DATE(lc.closed_at) ASC
    '''
    
    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    
    daily_data = []
    cumulative = 0
    
    for row in rows:
        daily_pnl = float(row['daily_pnl'] or 0)
        cumulative += daily_pnl
        daily_data.append({
            'date': row['date'],
            'pnl': round(daily_pnl, 2),
            'cumulative_pnl': round(cumulative, 2),
            'trades': row['trades'],
            'wins': row['wins'] or 0,
            'losses': row['losses'] or 0
        })
    
    return daily_data


def get_user_symbol_performance(user_id: int, period: str = 'all', limit: int = 10) -> List[Dict]:
    """
    Get top performing symbols for a user.
    
    Returns list of symbols with their PNL and trade count.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    start_date, end_date = get_date_filter_bounds(period)
    
    date_filter = ""
    params = [user_id]
    if start_date and end_date:
        date_filter = "AND lc.closed_at BETWEEN ? AND ?"
        params.extend([start_date, end_date])
    
    query = f'''
        SELECT 
            sl.symbol,
            sl.asset_type,
            COUNT(*) as trades,
            SUM(lc.pnl) as total_pnl,
            AVG(lc.pnl_percent) as avg_pnl_pct,
            SUM(CASE WHEN lc.pnl > 0 THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN lc.pnl <= 0 THEN 1 ELSE 0 END) as losses
        FROM lot_closures lc
        JOIN signal_lots sl ON lc.lot_id = sl.id
        WHERE (lc.user_id IS NULL OR lc.user_id = ?) {date_filter}
        GROUP BY sl.symbol, sl.asset_type
        ORDER BY total_pnl DESC
        LIMIT ?
    '''
    params.append(limit)
    
    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    
    symbols = []
    for row in rows:
        trades = row['trades'] or 0
        wins = row['wins'] or 0
        symbols.append({
            'symbol': row['symbol'],
            'asset_type': row['asset_type'],
            'trades': trades,
            'total_pnl': round(float(row['total_pnl'] or 0), 2),
            'avg_pnl_pct': round(float(row['avg_pnl_pct'] or 0), 1),
            'wins': wins,
            'losses': row['losses'] or 0,
            'win_rate': round((wins / trades * 100) if trades > 0 else 0, 1)
        })
    
    return symbols


def get_user_recent_trades(user_id: int, limit: int = 20) -> List[Dict]:
    """
    Get recent closed trades for a user.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Join path: lot_closures -> signal_lots (via lot_id) -> trades (via signal_id)
    query = '''
        SELECT 
            lc.id,
            sl.symbol,
            sl.asset_type,
            sl.strike,
            sl.expiry,
            sl.call_put,
            lc.closed_qty as quantity,
            sl.open_price as entry_price,
            lc.close_price as exit_price,
            lc.pnl,
            lc.pnl_percent,
            lc.holding_days,
            lc.closed_at,
            t.broker,
            t.source,
            t.risk_trigger
        FROM lot_closures lc
        JOIN signal_lots sl ON lc.lot_id = sl.id
        LEFT JOIN trades t ON sl.signal_id = t.id
        WHERE (lc.user_id IS NULL OR lc.user_id = ?)
        ORDER BY lc.closed_at DESC
        LIMIT ?
    '''
    
    cursor.execute(query, (user_id, limit))
    rows = cursor.fetchall()
    
    trades = []
    for row in rows:
        trade = {
            'id': row['id'],
            'symbol': row['symbol'],
            'asset_type': row['asset_type'],
            'strike': row['strike'],
            'expiry': row['expiry'],
            'call_put': row['call_put'],
            'quantity': row['quantity'],
            'entry_price': round(float(row['entry_price'] or 0), 2),
            'exit_price': round(float(row['exit_price'] or 0), 2),
            'pnl': round(float(row['pnl'] or 0), 2),
            'pnl_percent': round(float(row['pnl_percent'] or 0), 1),
            'holding_days': round(float(row['holding_days'] or 0), 1),
            'closed_at': row['closed_at'],
            'broker': row['broker'],
            'source': row['source'] or 'discord',
            'risk_trigger': row['risk_trigger']
        }
        trades.append(trade)
    
    return trades


# Database class wrapper for easy integration
class Database:
    """Thread-safe database wrapper"""
    
    def __init__(self):
        init_db()
    
    def get_connection(self):
        """Get thread-safe database connection"""
        return get_connection()
    
    def get_channels(self, category=None):
        return get_channels(category)
    
    def get_channel_by_id(self, channel_id):
        return get_channel_by_id(channel_id)
    
    def add_channel(self, discord_channel_id, name, category, broker_override=None):
        return add_channel(discord_channel_id, name, category, broker_override)
    
    def update_channel(self, channel_id, **kwargs):
        return update_channel(channel_id, **kwargs)
    
    def delete_channel(self, channel_id):
        return delete_channel(channel_id)
    
    def add_signal(self, discord_channel_id, message_id, signal_type, symbol, quantity, price=None, asset_type='stock', author_name=None, strike=None, expiry=None, call_put=None):
        return add_signal(discord_channel_id, message_id, signal_type, symbol, quantity, price, asset_type, author_name, strike, expiry, call_put)
    
    def add_trade(self, signal_data):
        return add_trade(signal_data)
    
    def get_trades(self, status=None, broker=None, limit=100):
        return get_trades(status, broker, limit)
    
    def update_trade(self, trade_id, **kwargs):
        return update_trade(trade_id, **kwargs)
    
    def create_lot(self, channel_id, signal_id, asset_type, symbol, quantity, open_price, opened_at, strike=None, expiry=None, call_put=None):
        return create_signal_lot(channel_id, signal_id, asset_type, symbol, quantity, open_price, opened_at, strike, expiry, call_put)
    
    def get_open_lots(self, channel_id, asset_type, symbol, strike=None, expiry=None, call_put=None):
        return get_open_lots(channel_id, asset_type, symbol, strike, expiry, call_put)
    
    def close_lot(self, lot_id, channel_id, signal_id, close_qty, close_price, closed_at):
        return close_lot(lot_id, channel_id, signal_id, close_qty, close_price, closed_at)
    
    def get_performance_metrics(self, channel_id=None, period_start=None, period_end=None):
        return get_performance_metrics(channel_id, period_start, period_end)
    
    def get_signal_history(self, channel_id=None, period='all', limit=100):
        return get_signal_history(channel_id, period, limit)
    
    def find_open_bto_trade(self, symbol: str, asset_type: str, broker: str = None,
                            strike: float = None, expiry: str = None, call_put: str = None):
        return find_open_bto_trade(symbol, asset_type, broker, strike, expiry, call_put)
    
    def get_risk_management_settings(self):
        return get_risk_management_settings()
    
    def save_setting(self, key: str, value):
        return save_setting(key, value)
    
    def get_setting(self, key: str, default=None):
        return get_setting(key, default)


if __name__ == '__main__':
    init_db()
    print("Database initialized successfully")

# ============ SLIPPAGE SETTINGS ============

def get_slippage_settings() -> Dict[str, Any]:
    """Get current slippage protection settings"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT enabled, threshold_percent, updated_at
        FROM slippage_settings
        WHERE id = 1
    ''')
    
    row = cursor.fetchone()
    if row:
        return {
            'enabled': bool(row['enabled']),
            'threshold_percent': float(row['threshold_percent']),
            'updated_at': row['updated_at']
        }
    
    # Return defaults if not found
    return {
        'enabled': True,
        'threshold_percent': 10.0,
        'updated_at': None
    }


def update_slippage_settings(enabled: bool, threshold_percent: float) -> bool:
    """Update slippage protection settings"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE slippage_settings
            SET enabled = ?,
                threshold_percent = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''', (1 if enabled else 0, float(threshold_percent)))
        
        conn.commit()
        return True
    except Exception as e:
        print(f"[DATABASE] Error updating slippage settings: {e}")
        return False


# ============ POSITION RISK MANAGEMENT ============

def get_position_risk_settings(trade_id: int) -> Dict[str, Any]:
    """Get risk settings for a specific trade"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT profit_target_percent, stop_loss_percent, 
               trailing_stop_enabled, trailing_stop_percent, updated_at
        FROM position_risk_settings
        WHERE trade_id = ?
    ''', (trade_id,))
    
    row = cursor.fetchone()
    if row:
        return {
            'profit_target_percent': float(row['profit_target_percent']),
            'stop_loss_percent': float(row['stop_loss_percent']),
            'trailing_stop_enabled': bool(row['trailing_stop_enabled']),
            'trailing_stop_percent': float(row['trailing_stop_percent']),
            'updated_at': row['updated_at']
        }
    
    # Return defaults if not found
    return {
        'profit_target_percent': 20.0,
        'stop_loss_percent': 10.0,
        'trailing_stop_enabled': False,
        'trailing_stop_percent': 5.0,
        'updated_at': None
    }


def update_position_risk_settings(trade_id: int, profit_target: float = None, 
                                   stop_loss: float = None, trailing_stop_enabled: bool = None,
                                   trailing_stop: float = None) -> bool:
    """Update or create risk settings for a trade"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Check if settings exist
        existing = get_position_risk_settings(trade_id)
        
        # Prepare values (use existing if not provided)
        profit_target = profit_target if profit_target is not None else existing['profit_target_percent']
        stop_loss = stop_loss if stop_loss is not None else existing['stop_loss_percent']
        trailing_stop_enabled = trailing_stop_enabled if trailing_stop_enabled is not None else existing['trailing_stop_enabled']
        trailing_stop = trailing_stop if trailing_stop is not None else existing['trailing_stop_percent']
        
        # Insert or replace
        cursor.execute('''
            INSERT INTO position_risk_settings (trade_id, profit_target_percent, stop_loss_percent, 
                                                 trailing_stop_enabled, trailing_stop_percent, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(trade_id) DO UPDATE SET
                profit_target_percent = excluded.profit_target_percent,
                stop_loss_percent = excluded.stop_loss_percent,
                trailing_stop_enabled = excluded.trailing_stop_enabled,
                trailing_stop_percent = excluded.trailing_stop_percent,
                updated_at = CURRENT_TIMESTAMP
        ''', (trade_id, float(profit_target), float(stop_loss), 
              1 if trailing_stop_enabled else 0, float(trailing_stop)))
        
        conn.commit()
        return True
    except Exception as e:
        print(f"[DATABASE] Error updating position risk settings: {e}")
        return False


# ============ GLOBAL RISK MANAGEMENT SETTINGS ============

def get_risk_management_settings() -> Dict[str, Any]:
    """Get global risk management settings"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT enabled, profit_target_percent, stop_loss_percent, trailing_stop_percent, updated_at
        FROM risk_management_settings
        WHERE id = 1
    ''')
    
    row = cursor.fetchone()
    if row:
        return {
            'enabled': bool(row['enabled']),
            'profit_target_percent': float(row['profit_target_percent']),
            'stop_loss_percent': float(row['stop_loss_percent']),
            'trailing_stop_percent': float(row['trailing_stop_percent']),
            'updated_at': row['updated_at']
        }
    
    return {
        'enabled': False,
        'profit_target_percent': 20.0,
        'stop_loss_percent': 10.0,
        'trailing_stop_percent': 5.0,
        'updated_at': None
    }


def update_risk_management_settings(enabled: bool, profit_target_percent: float, 
                                     stop_loss_percent: float, trailing_stop_percent: float) -> bool:
    """Update global risk management settings"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE risk_management_settings
            SET enabled = ?,
                profit_target_percent = ?,
                stop_loss_percent = ?,
                trailing_stop_percent = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''', (1 if enabled else 0, float(profit_target_percent), 
              float(stop_loss_percent), float(trailing_stop_percent)))
        
        conn.commit()
        return True
    except Exception as e:
        print(f"[DATABASE] Error updating risk management settings: {e}")
        return False


# ============ AI SETTINGS ============

def get_ai_settings() -> Dict[str, Any]:
    """Get AI analysis settings"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT enabled, model, sentiment_enabled, updated_at
        FROM ai_settings
        WHERE id = 1
    ''')
    
    row = cursor.fetchone()
    if row:
        return {
            'enabled': bool(row['enabled']),
            'model': row['model'],
            'sentiment_enabled': bool(row['sentiment_enabled']),
            'updated_at': row['updated_at']
        }
    
    return {
        'enabled': True,
        'model': 'gpt-4o-mini',
        'sentiment_enabled': False,
        'updated_at': None
    }


def update_ai_settings(enabled: bool, model: str, sentiment_enabled: bool) -> bool:
    """Update AI analysis settings"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE ai_settings
            SET enabled = ?,
                model = ?,
                sentiment_enabled = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''', (1 if enabled else 0, model, 1 if sentiment_enabled else 0))
        
        conn.commit()
        return True
    except Exception as e:
        print(f"[DATABASE] Error updating AI settings: {e}")
        return False


# ============ TELEGRAM SETTINGS ============

def get_telegram_settings() -> Dict[str, Any]:
    """Get Telegram integration settings"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT enabled, api_id, api_hash, phone_number, session_string, 
                   session_status, last_connected_at, updated_at
            FROM telegram_settings
            WHERE id = 1
        ''')
        
        row = cursor.fetchone()
        if row:
            return {
                'enabled': bool(row['enabled']),
                'api_id': row['api_id'] or '',
                'api_hash': row['api_hash'] or '',
                'phone_number': row['phone_number'] or '',
                'session_string': row['session_string'] or '',
                'session_status': row['session_status'] or 'disconnected',
                'last_connected_at': row['last_connected_at'],
                'updated_at': row['updated_at']
            }
    except Exception as e:
        print(f"[DATABASE] Error getting Telegram settings: {e}")
    
    return {
        'enabled': False,
        'api_id': '',
        'api_hash': '',
        'phone_number': '',
        'session_string': '',
        'session_status': 'disconnected',
        'last_connected_at': None,
        'updated_at': None
    }


def update_telegram_settings(enabled: bool = None, api_id: str = None, api_hash: str = None,
                              phone_number: str = None, session_string: str = None,
                              session_status: str = None) -> bool:
    """Update Telegram integration settings"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        updates = []
        values = []
        
        if enabled is not None:
            updates.append('enabled = ?')
            values.append(1 if enabled else 0)
        if api_id is not None:
            updates.append('api_id = ?')
            values.append(api_id)
        if api_hash is not None:
            updates.append('api_hash = ?')
            values.append(api_hash)
        if phone_number is not None:
            updates.append('phone_number = ?')
            values.append(phone_number)
        if session_string is not None:
            updates.append('session_string = ?')
            values.append(session_string)
        if session_status is not None:
            updates.append('session_status = ?')
            values.append(session_status)
            if session_status == 'connected':
                updates.append('last_connected_at = CURRENT_TIMESTAMP')
        
        updates.append('updated_at = CURRENT_TIMESTAMP')
        
        cursor.execute(f'''
            UPDATE telegram_settings
            SET {', '.join(updates)}
            WHERE id = 1
        ''', values)
        
        conn.commit()
        return True
    except Exception as e:
        print(f"[DATABASE] Error updating Telegram settings: {e}")
        return False


def get_telegram_channels() -> List[Dict[str, Any]]:
    """Get all Telegram channels (platform = 'telegram')"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, name, telegram_chat_id, telegram_chat_type, telegram_username,
               execute_enabled, track_enabled, broker_override, enabled_brokers,
               risk_management_enabled, position_size_pct, profit_target_1_pct,
               profit_target_2_pct, profit_target_3_pct, stop_loss_pct,
               trailing_stop_pct, trailing_activation_pct, exit_strategy_mode,
               default_quantity, is_active, created_at, market
        FROM channels
        WHERE platform = 'telegram'
        ORDER BY name
    ''')
    
    channels = []
    for row in cursor.fetchall():
        channels.append({
            'id': row['id'],
            'name': row['name'],
            'telegram_chat_id': row['telegram_chat_id'],
            'telegram_chat_type': row['telegram_chat_type'],
            'telegram_username': row['telegram_username'],
            'execute_enabled': bool(row['execute_enabled']),
            'track_enabled': bool(row['track_enabled']),
            'broker_override': row['broker_override'],
            'enabled_brokers': json.loads(row['enabled_brokers']) if row['enabled_brokers'] else [],
            'risk_management_enabled': bool(row['risk_management_enabled']),
            'position_size_pct': row['position_size_pct'],
            'profit_target_1_pct': row['profit_target_1_pct'],
            'profit_target_2_pct': row['profit_target_2_pct'],
            'profit_target_3_pct': row['profit_target_3_pct'],
            'stop_loss_pct': row['stop_loss_pct'],
            'trailing_stop_pct': row['trailing_stop_pct'],
            'trailing_activation_pct': row['trailing_activation_pct'],
            'exit_strategy_mode': row['exit_strategy_mode'] or 'signal',
            'default_quantity': row['default_quantity'],
            'is_active': bool(row['is_active']),
            'created_at': row['created_at'],
            'market': row['market'] or 'US'
        })
    
    return channels


def add_telegram_channel(telegram_chat_id: str, name: str, chat_type: str = 'group',
                          username: str = None, category: str = 'TRACK',
                          execute_enabled: bool = False, track_enabled: bool = True,
                          market: str = 'US', enabled_brokers: list = None) -> Optional[int]:
    """Add a new Telegram channel with proper execution/tracking settings
    
    Args:
        telegram_chat_id: Telegram chat ID (numeric or @username)
        name: Channel display name
        chat_type: Type of chat (group, channel, etc.)
        username: Telegram username if applicable
        category: EXECUTE or TRACK
        execute_enabled: Whether to execute trades (queue signals)
        track_enabled: Whether to track signals for PNL
        market: US, IN (India), or CA (Canada)
        enabled_brokers: List of broker names to use for execution
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # If category is EXECUTE, default execute_enabled to True
    if category == 'EXECUTE' and not execute_enabled:
        execute_enabled = True
    
    # Serialize enabled_brokers to JSON
    brokers_json = json.dumps(enabled_brokers) if enabled_brokers else None
    
    try:
        cursor.execute('''
            INSERT INTO channels (discord_channel_id, name, category, platform, 
                                  telegram_chat_id, telegram_chat_type, telegram_username,
                                  execute_enabled, track_enabled, market, enabled_brokers)
            VALUES (?, ?, ?, 'telegram', ?, ?, ?, ?, ?, ?, ?)
        ''', (f'tg_{telegram_chat_id}', name, category, telegram_chat_id, chat_type, 
              username, 1 if execute_enabled else 0, 1 if track_enabled else 0, 
              market, brokers_json))
        
        conn.commit()
        print(f"[DATABASE] Telegram channel added: {name} (execute={execute_enabled}, track={track_enabled}, market={market})")
        return cursor.lastrowid
    except Exception as e:
        print(f"[DATABASE] Error adding Telegram channel: {e}")
        return None


def get_channel_by_telegram_id(telegram_chat_id: str) -> Optional[Dict[str, Any]]:
    """Get channel settings by Telegram chat ID (unified lookup for both platforms)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    chat_id_str = str(telegram_chat_id)
    normalized_id = chat_id_str.lstrip('@').lstrip('-')
    if normalized_id.startswith('100'):
        normalized_id = normalized_id[3:]
    
    cursor.execute('''
        SELECT id, name, discord_channel_id, telegram_chat_id, telegram_username, platform,
               execute_enabled, track_enabled, broker_override, enabled_brokers,
               risk_management_enabled, position_size_pct, profit_target_1_pct,
               profit_target_2_pct, profit_target_3_pct, stop_loss_pct,
               trailing_stop_pct, trailing_activation_pct, exit_strategy_mode,
               default_quantity, is_active
        FROM channels
        WHERE telegram_chat_id = ? 
           OR telegram_username = ? 
           OR REPLACE(REPLACE(telegram_chat_id, '-100', ''), '-', '') = ?
        LIMIT 1
    ''', (chat_id_str, chat_id_str.lstrip('@'), normalized_id))
    
    row = cursor.fetchone()
    if not row:
        return None
    
    return {
        'id': row['id'],
        'name': row['name'],
        'discord_channel_id': row['discord_channel_id'],
        'telegram_chat_id': row['telegram_chat_id'],
        'telegram_username': row['telegram_username'],
        'platform': row['platform'],
        'execute_enabled': bool(row['execute_enabled']),
        'track_enabled': bool(row['track_enabled']),
        'broker_override': row['broker_override'],
        'enabled_brokers': json.loads(row['enabled_brokers']) if row['enabled_brokers'] else [],
        'risk_management_enabled': bool(row['risk_management_enabled']),
        'position_size_pct': row['position_size_pct'],
        'profit_target_1_pct': row['profit_target_1_pct'],
        'profit_target_2_pct': row['profit_target_2_pct'],
        'profit_target_3_pct': row['profit_target_3_pct'],
        'stop_loss_pct': row['stop_loss_pct'],
        'trailing_stop_pct': row['trailing_stop_pct'],
        'trailing_activation_pct': row['trailing_activation_pct'],
        'exit_strategy_mode': row['exit_strategy_mode'] or 'signal',
        'default_quantity': row['default_quantity'],
        'is_active': bool(row['is_active'])
    }


# ============ TRADING SETTINGS ============

def get_trading_settings() -> Dict[str, Any]:
    """Get trading settings"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Ensure trade_summary_channel column exists
    try:
        cursor.execute("PRAGMA table_info(trading_settings)")
        columns = {row['name'] for row in cursor.fetchall()}
        if 'trade_summary_channel' not in columns:
            cursor.execute('ALTER TABLE trading_settings ADD COLUMN trade_summary_channel TEXT DEFAULT ""')
            conn.commit()
    except Exception as e:
        print(f"[DATABASE] Error adding trade_summary_channel column: {e}")
    
    cursor.execute('''
        SELECT max_position_size, updated_at, global_default_quantity, max_position_size_enabled, trade_summary_enabled, trade_summary_channel
        FROM trading_settings
        WHERE id = 1
    ''')
    
    row = cursor.fetchone()
    if row:
        return {
            'max_position_size': int(row['max_position_size']),
            'updated_at': row['updated_at'],
            'global_default_quantity': row['global_default_quantity'],
            'max_position_size_enabled': bool(row['max_position_size_enabled']) if row['max_position_size_enabled'] is not None else True,
            'trade_summary_enabled': bool(row['trade_summary_enabled']) if row['trade_summary_enabled'] is not None else True,
            'trade_summary_channel': row['trade_summary_channel'] or ''
        }
    
    return {
        'max_position_size': 600,
        'updated_at': None,
        'global_default_quantity': None,
        'max_position_size_enabled': True,
        'trade_summary_enabled': True,
        'trade_summary_channel': ''
    }


def update_trading_settings(max_position_size: int, global_default_quantity: int = None, max_position_size_enabled: bool = True, trade_summary_enabled: bool = True, trade_summary_channel: str = '') -> bool:
    """Update trading settings"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Ensure trade_summary_channel column exists
        cursor.execute("PRAGMA table_info(trading_settings)")
        columns = {row['name'] for row in cursor.fetchall()}
        if 'trade_summary_channel' not in columns:
            cursor.execute('ALTER TABLE trading_settings ADD COLUMN trade_summary_channel TEXT DEFAULT ""')
            conn.commit()
        
        cursor.execute('''
            UPDATE trading_settings
            SET max_position_size = ?,
                global_default_quantity = ?,
                max_position_size_enabled = ?,
                trade_summary_enabled = ?,
                trade_summary_channel = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''', (int(max_position_size), global_default_quantity, 1 if max_position_size_enabled else 0, 1 if trade_summary_enabled else 0, trade_summary_channel or ''))
        
        conn.commit()
        return True
    except Exception as e:
        print(f"[DATABASE] Error updating trading settings: {e}")
        return False


def is_trade_summary_enabled(channel_id: str = None) -> bool:
    """Check if trade summary posting is enabled.
    
    Checks both global setting and per-channel setting (if channel_id provided).
    Returns True only if both global AND channel settings allow it.
    
    Args:
        channel_id: Optional Discord channel ID to check per-channel setting
        
    Returns:
        True if trade summary should be posted, False otherwise
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Check global setting first
    try:
        cursor.execute('SELECT trade_summary_enabled FROM trading_settings WHERE id = 1')
        row = cursor.fetchone()
        global_enabled = bool(row['trade_summary_enabled']) if row and row['trade_summary_enabled'] is not None else True
        
        if not global_enabled:
            return False  # Global disabled, skip channel check
    except Exception as e:
        print(f"[DATABASE] Error checking global trade_summary_enabled: {e}")
        global_enabled = True  # Default to enabled on error
    
    # If no channel_id, return global setting
    if not channel_id:
        return global_enabled
    
    # Check per-channel setting
    try:
        cursor.execute('SELECT trade_summary_enabled FROM channels WHERE discord_channel_id = ?', (str(channel_id),))
        row = cursor.fetchone()
        if row and row['trade_summary_enabled'] is not None:
            return bool(row['trade_summary_enabled'])
        return True  # Default to enabled if not set
    except Exception as e:
        print(f"[DATABASE] Error checking channel trade_summary_enabled: {e}")
        return True  # Default to enabled on error


# ============ DISCORD SETTINGS ============

def get_discord_settings() -> Dict[str, Any]:
    """Get Discord settings from database"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT allow_self_messages, discovery_mode, option_pattern, stock_pattern, 
                   allowed_author_ids, allowed_guild_ids, updated_at
            FROM discord_settings
            WHERE id = 1
        ''')
        
        row = cursor.fetchone()
        if row:
            return {
                'allow_self_messages': bool(row['allow_self_messages']),
                'discovery_mode': bool(row['discovery_mode']),
                'option_pattern': row['option_pattern'] or '',
                'stock_pattern': row['stock_pattern'] or '',
                'allowed_author_ids': row['allowed_author_ids'] or '',
                'allowed_guild_ids': row['allowed_guild_ids'] or '',
                'updated_at': row['updated_at']
            }
    except Exception as e:
        print(f"[DATABASE] Error getting Discord settings: {e}")
    
    return {
        'allow_self_messages': False,
        'discovery_mode': False,
        'option_pattern': r'^(BTO|STC)\s+(?:(\d+)\s+)?\$?([A-Za-z]+)\s+\$?([\d.]+)\s*([CPcp])\s*(\d{1,2}/\d{1,2})\s*@?\s*([\d.]+|[mM])',
        'stock_pattern': r'^(BTO|STC)\s+(?:(\d+)\s+)?\$?([A-Za-z]+)\s*@?\s*([\d.]+|[mM])',
        'allowed_author_ids': '',
        'allowed_guild_ids': '',
        'updated_at': None
    }


def update_discord_settings(allow_self_messages: bool, discovery_mode: bool, 
                            option_pattern: str, stock_pattern: str,
                            allowed_author_ids: str, allowed_guild_ids: str) -> bool:
    """Update Discord settings in database"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE discord_settings
            SET allow_self_messages = ?,
                discovery_mode = ?,
                option_pattern = ?,
                stock_pattern = ?,
                allowed_author_ids = ?,
                allowed_guild_ids = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''', (1 if allow_self_messages else 0, 1 if discovery_mode else 0,
              option_pattern, stock_pattern, allowed_author_ids, allowed_guild_ids))
        
        if cursor.rowcount == 0:
            cursor.execute('''
                INSERT INTO discord_settings 
                (id, allow_self_messages, discovery_mode, option_pattern, stock_pattern, allowed_author_ids, allowed_guild_ids)
                VALUES (1, ?, ?, ?, ?, ?, ?)
            ''', (1 if allow_self_messages else 0, 1 if discovery_mode else 0,
                  option_pattern, stock_pattern, allowed_author_ids, allowed_guild_ids))
        
        conn.commit()
        print("[DATABASE] ✓ Discord settings updated")
        return True
    except Exception as e:
        print(f"[DATABASE] Error updating Discord settings: {e}")
        return False


# ============ GENERIC SETTINGS ============

def get_setting(key: str, default: str = None) -> str:
    """Get a generic setting value from the settings table"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
        row = cursor.fetchone()
        if row:
            return row['value']
        return default
    except Exception as e:
        print(f"[DATABASE] Error getting setting '{key}': {e}")
        return default


def save_setting(key: str, value: str) -> bool:
    """Save a generic setting value to the settings table"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP
        ''', (key, value, value))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DATABASE] Error saving setting '{key}': {e}")
        return False


# ============ EXTENDED HOURS SETTINGS ============

def get_broker_extended_hours(broker: str) -> bool:
    """Get extended hours trading setting for a broker.
    
    Args:
        broker: Broker name (schwab, alpaca, ibkr, robinhood, webull)
        
    Returns:
        True if extended hours trading is enabled for this broker
    """
    key = f"{broker.lower()}_extended_hours"
    value = get_setting(key, 'false')
    return value.lower() == 'true'


def set_broker_extended_hours(broker: str, enabled: bool) -> bool:
    """Set extended hours trading setting for a broker.
    
    Args:
        broker: Broker name (schwab, alpaca, ibkr, robinhood, webull)
        enabled: True to enable extended hours trading
        
    Returns:
        True if setting was saved successfully
    """
    key = f"{broker.lower()}_extended_hours"
    return save_setting(key, 'true' if enabled else 'false')


def get_all_extended_hours_settings() -> Dict[str, bool]:
    """Get extended hours settings for all brokers"""
    brokers = ['schwab', 'alpaca', 'ibkr', 'robinhood', 'webull']
    return {broker: get_broker_extended_hours(broker) for broker in brokers}


# ============ ALPACA SETTINGS ============

def get_alpaca_settings() -> Dict[str, str]:
    """Get Alpaca API credentials from database"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT key, value FROM settings WHERE key IN ("alpaca_api_key", "alpaca_secret_key")')
        rows = cursor.fetchall()
        settings = {}
        for row in rows:
            settings[row['key']] = row['value'] or ''
        return settings
    except Exception as e:
        print(f"[DATABASE] Error getting Alpaca settings: {e}")
        return {'alpaca_api_key': '', 'alpaca_secret_key': ''}


def update_alpaca_settings(api_key: str, secret_key: str) -> bool:
    """Update Alpaca API credentials in database"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', ('alpaca_api_key', api_key))
        
        cursor.execute('''
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', ('alpaca_secret_key', secret_key))
        
        conn.commit()
        print("[DATABASE] ✓ Alpaca credentials updated")
        return True
    except Exception as e:
        print(f"[DATABASE] Error updating Alpaca settings: {e}")
        return False

# ============ ALPACA LIVE SETTINGS ============

def get_alpaca_live_settings() -> Dict[str, str]:
    """Get Alpaca Live API credentials from database"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT key, value FROM settings WHERE key IN ("alpaca_live_api_key", "alpaca_live_secret_key")')
        rows = cursor.fetchall()
        settings = {}
        for row in rows:
            settings[row['key']] = row['value'] or ''
        return settings
    except Exception as e:
        print(f"[DATABASE] Error getting Alpaca Live settings: {e}")
        return {'alpaca_live_api_key': '', 'alpaca_live_secret_key': ''}


def update_alpaca_live_settings(api_key: str, secret_key: str) -> bool:
    """Update Alpaca Live API credentials in database"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', ('alpaca_live_api_key', api_key))
        
        cursor.execute('''
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', ('alpaca_live_secret_key', secret_key))
        
        conn.commit()
        print("[DATABASE] ✓ Alpaca Live credentials updated")
        return True
    except Exception as e:
        print(f"[DATABASE] Error updating Alpaca Live settings: {e}")
        return False


# ============ ROBINHOOD SETTINGS ============

def get_robinhood_settings() -> Dict[str, str]:
    """Get Robinhood credentials from database
    
    Checks both settings table (legacy) and broker_credentials_service (new).
    Falls back to broker_credentials_service if settings table is empty.
    
    WARNING: Robinhood has NO paper trading mode.
    All trades are executed with REAL money.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT key, value FROM settings WHERE key IN ("robinhood_username", "robinhood_password", "robinhood_totp_secret")')
        rows = cursor.fetchall()
        settings = {}
        for row in rows:
            settings[row['key']] = row['value'] or ''
        
        if settings.get('robinhood_username'):
            print(f"[DATABASE] ✓ Robinhood credentials loaded from settings table")
            return settings
        
        try:
            from .broker_credentials_service import get_robinhood_credentials
            creds = get_robinhood_credentials()
            print(f"[DATABASE] Robinhood broker_credentials_service returned: username={bool(creds.get('username'))}, password={bool(creds.get('password'))}")
            if creds.get('username'):
                return {
                    'robinhood_username': creds.get('username', ''),
                    'robinhood_password': creds.get('password', ''),
                    'robinhood_totp_secret': creds.get('totp_secret', '')
                }
            else:
                print(f"[DATABASE] ⚠️ Robinhood: broker_credentials_service returned empty credentials")
        except Exception as e:
            print(f"[DATABASE] Fallback to broker_credentials_service failed: {e}")
        
        print(f"[DATABASE] ⚠️ Robinhood: No credentials found in either settings table or broker_credentials_service")
        return settings if settings else {'robinhood_username': '', 'robinhood_password': '', 'robinhood_totp_secret': ''}
    except Exception as e:
        print(f"[DATABASE] Error getting Robinhood settings: {e}")
        return {'robinhood_username': '', 'robinhood_password': '', 'robinhood_totp_secret': ''}


def update_robinhood_settings(username: str, password: str, totp_secret: str) -> bool:
    """Update Robinhood credentials in database
    
    Args:
        username: Robinhood account email
        password: Robinhood account password
        totp_secret: 2FA TOTP secret from authenticator setup
    
    WARNING: Robinhood has NO paper trading mode.
    All trades are executed with REAL money.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', ('robinhood_username', username))
        
        cursor.execute('''
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', ('robinhood_password', password))
        
        cursor.execute('''
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', ('robinhood_totp_secret', totp_secret))
        
        conn.commit()
        print("[DATABASE] ✓ Robinhood credentials updated (WARNING: LIVE trading only)")
        return True
    except Exception as e:
        print(f"[DATABASE] Error updating Robinhood settings: {e}")
        return False


# ============ SIGNAL CONVERSION SETTINGS ============

def get_signal_conversion_settings() -> Dict[str, Any]:
    """
    Get signal conversion settings from database
    Returns dict with conversion_channel_id, target_execution_channel_id, 
    notification_channel_id, and notifications_enabled
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT value FROM settings WHERE key = ?', ('conversion_channel_id',))
        conversion_row = cursor.fetchone()
        conversion_channel_id = conversion_row['value'] if conversion_row else ''
        
        cursor.execute('SELECT value FROM settings WHERE key = ?', ('target_execution_channel_id',))
        target_row = cursor.fetchone()
        target_execution_channel_id = target_row['value'] if target_row else ''
        
        cursor.execute('SELECT value FROM settings WHERE key = ?', ('notification_channel_id',))
        notif_row = cursor.fetchone()
        notification_channel_id = notif_row['value'] if notif_row else ''
        
        cursor.execute('SELECT value FROM settings WHERE key = ?', ('notifications_enabled',))
        notif_enabled_row = cursor.fetchone()
        notifications_enabled = notif_enabled_row['value'] == '1' if notif_enabled_row else True
        
        return {
            'conversion_channel_id': conversion_channel_id,
            'target_execution_channel_id': target_execution_channel_id,
            'notification_channel_id': notification_channel_id,
            'notifications_enabled': notifications_enabled
        }
    except Exception as e:
        print(f"[DATABASE] Error getting signal conversion settings: {e}")
        return {
            'conversion_channel_id': '',
            'target_execution_channel_id': '',
            'notification_channel_id': '',
            'notifications_enabled': True
        }

def save_signal_conversion_settings(conversion_channel_id: str, target_execution_channel_id: str, 
                                     notification_channel_id: str = None, notifications_enabled: bool = None) -> bool:
    """
    Save signal conversion settings to database
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Save conversion channel ID
        cursor.execute('''
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP
        ''', ('conversion_channel_id', conversion_channel_id, conversion_channel_id))
        
        # Save target execution channel ID
        cursor.execute('''
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP
        ''', ('target_execution_channel_id', target_execution_channel_id, target_execution_channel_id))
        
        # Save notification channel ID if provided
        if notification_channel_id is not None:
            cursor.execute('''
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP
            ''', ('notification_channel_id', notification_channel_id, notification_channel_id))
        
        # Save notifications enabled if provided
        if notifications_enabled is not None:
            cursor.execute('''
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP
            ''', ('notifications_enabled', '1' if notifications_enabled else '0', '1' if notifications_enabled else '0'))
        
        conn.commit()
        print(f"[DATABASE] ✓ Saved signal conversion settings")
        return True
    except Exception as e:
        print(f"[DATABASE] Error saving signal conversion settings: {e}")
        conn.rollback()
        return False


# ============ CHANNEL MAPPINGS (SOURCE CHANNEL TO WEBHOOK URL) ============

def init_channel_mappings_table():
    """Create channel_mappings table if it doesn't exist - maps source channels to webhook URLs or destination channel IDs"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS channel_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_channel_id TEXT NOT NULL,
            source_channel_name TEXT DEFAULT '',
            destination_type TEXT DEFAULT 'webhook',
            webhook_url TEXT DEFAULT '',
            webhook_name TEXT DEFAULT '',
            destination_channel_id TEXT DEFAULT '',
            destination_channel_name TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            forward_enabled INTEGER DEFAULT 1,
            execute_on_source INTEGER DEFAULT 0,
            format_as_bto_stc INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Migration: Add new columns if they don't exist
    try:
        cursor.execute("PRAGMA table_info(channel_mappings)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'forward_enabled' not in columns:
            cursor.execute('ALTER TABLE channel_mappings ADD COLUMN forward_enabled INTEGER DEFAULT 1')
            print("[DATABASE] ✓ Added forward_enabled column to channel_mappings")
        
        if 'execute_on_source' not in columns:
            cursor.execute('ALTER TABLE channel_mappings ADD COLUMN execute_on_source INTEGER DEFAULT 0')
            print("[DATABASE] ✓ Added execute_on_source column to channel_mappings")
        
        if 'format_as_bto_stc' not in columns:
            cursor.execute('ALTER TABLE channel_mappings ADD COLUMN format_as_bto_stc INTEGER DEFAULT 1')
            print("[DATABASE] ✓ Added format_as_bto_stc column to channel_mappings")
        
        if 'destination_type' not in columns:
            cursor.execute("ALTER TABLE channel_mappings ADD COLUMN destination_type TEXT DEFAULT 'webhook'")
            print("[DATABASE] ✓ Added destination_type column to channel_mappings")
        
        if 'destination_channel_id' not in columns:
            cursor.execute('ALTER TABLE channel_mappings ADD COLUMN destination_channel_id TEXT DEFAULT ""')
            print("[DATABASE] ✓ Added destination_channel_id column to channel_mappings")
        
        if 'destination_channel_name' not in columns:
            cursor.execute('ALTER TABLE channel_mappings ADD COLUMN destination_channel_name TEXT DEFAULT ""')
            print("[DATABASE] ✓ Added destination_channel_name column to channel_mappings")
    except Exception as e:
        pass  # Columns already exist or table just created
    
    conn.commit()
    print("[DATABASE] ✓ Channel mappings table ready")


def migrate_channel_mappings_to_webhook():
    """Migrate old channel_mappings table to add new columns if needed"""
    pass


def get_channel_mappings() -> List[Dict[str, Any]]:
    """Get all channel mappings"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        init_channel_mappings_table()
        
        cursor.execute('''
            SELECT id, source_channel_id, source_channel_name, 
                   COALESCE(destination_type, 'webhook') as destination_type,
                   COALESCE(webhook_url, '') as webhook_url, 
                   COALESCE(webhook_name, '') as webhook_name,
                   COALESCE(destination_channel_id, '') as destination_channel_id,
                   COALESCE(destination_channel_name, '') as destination_channel_name,
                   is_active, 
                   COALESCE(forward_enabled, 1) as forward_enabled,
                   COALESCE(execute_on_source, 0) as execute_on_source,
                   COALESCE(format_as_bto_stc, 1) as format_as_bto_stc,
                   created_at, updated_at
            FROM channel_mappings
            ORDER BY created_at DESC
        ''')
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"[DATABASE] Error getting channel mappings: {e}")
        return []


def get_destination_for_source(source_channel_id: str) -> Optional[str]:
    """Get webhook URL for a source channel (for signal forwarding).
    Returns the webhook URL if an active mapping exists, None otherwise."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        init_channel_mappings_table()
        
        cursor.execute('''
            SELECT webhook_url FROM channel_mappings
            WHERE source_channel_id = ? AND is_active = 1
            LIMIT 1
        ''', (source_channel_id,))
        
        row = cursor.fetchone()
        if row and row['webhook_url']:
            return row['webhook_url']
        return None
    except Exception as e:
        return None


def get_mapping_config_for_source(source_channel_id: str) -> Optional[Dict[str, Any]]:
    """Get full mapping configuration for a source channel.
    Returns dict with all mapping settings if active mapping exists, None otherwise.
    
    Returns:
        {
            'destination_type': str ('webhook' or 'channel'),
            'webhook_url': str,
            'webhook_name': str,
            'destination_channel_id': str,
            'destination_channel_name': str,
            'forward_enabled': bool,
            'execute_on_source': bool,
            'format_as_bto_stc': bool
        }
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        init_channel_mappings_table()
        
        cursor.execute('''
            SELECT COALESCE(destination_type, 'webhook') as destination_type,
                   COALESCE(webhook_url, '') as webhook_url, 
                   COALESCE(webhook_name, '') as webhook_name,
                   COALESCE(destination_channel_id, '') as destination_channel_id,
                   COALESCE(destination_channel_name, '') as destination_channel_name,
                   COALESCE(forward_enabled, 1) as forward_enabled,
                   COALESCE(execute_on_source, 0) as execute_on_source,
                   COALESCE(format_as_bto_stc, 1) as format_as_bto_stc
            FROM channel_mappings
            WHERE source_channel_id = ? AND is_active = 1
            LIMIT 1
        ''', (source_channel_id,))
        
        row = cursor.fetchone()
        if row:
            dest_type = row['destination_type']
            has_destination = (dest_type == 'webhook' and row['webhook_url']) or \
                              (dest_type == 'channel' and row['destination_channel_id'])
            
            if has_destination:
                return {
                    'destination_type': dest_type,
                    'webhook_url': row['webhook_url'] or '',
                    'webhook_name': row['webhook_name'] or '',
                    'destination_channel_id': row['destination_channel_id'] or '',
                    'destination_channel_name': row['destination_channel_name'] or '',
                    'forward_enabled': bool(row['forward_enabled']),
                    'execute_on_source': bool(row['execute_on_source']),
                    'format_as_bto_stc': bool(row['format_as_bto_stc'])
                }
        return None
    except Exception as e:
        print(f"[DATABASE] Error getting mapping config: {e}")
        return None


def add_channel_mapping(source_channel_id: str, webhook_url: str = '',
                        source_channel_name: str = '', webhook_name: str = '',
                        forward_enabled: bool = True, execute_on_source: bool = False,
                        format_as_bto_stc: bool = True,
                        destination_type: str = 'webhook',
                        destination_channel_id: str = '',
                        destination_channel_name: str = '') -> Dict[str, Any]:
    """Add a new channel mapping (source channel -> webhook URL or destination channel)
    
    Args:
        source_channel_id: Discord channel ID to monitor
        webhook_url: Destination webhook URL (if destination_type='webhook')
        source_channel_name: Human-readable source channel name
        webhook_name: Human-readable webhook name
        forward_enabled: Whether to forward signals (default True)
        execute_on_source: Whether to ALSO execute trades on broker (default False)
        format_as_bto_stc: Whether to format options as BTO/STC (default True)
        destination_type: 'webhook' or 'channel' (default 'webhook')
        destination_channel_id: Destination Discord channel ID (if destination_type='channel')
        destination_channel_name: Human-readable destination channel name
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        init_channel_mappings_table()
        
        cursor.execute('''
            INSERT INTO channel_mappings (source_channel_id, source_channel_name, 
                                          destination_type, webhook_url, webhook_name,
                                          destination_channel_id, destination_channel_name,
                                          forward_enabled, execute_on_source, format_as_bto_stc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (source_channel_id.strip(), source_channel_name.strip(), 
              destination_type.strip(),
              webhook_url.strip() if webhook_url else '',
              webhook_name.strip() if webhook_name else '',
              destination_channel_id.strip() if destination_channel_id else '',
              destination_channel_name.strip() if destination_channel_name else '',
              1 if forward_enabled else 0,
              1 if execute_on_source else 0,
              1 if format_as_bto_stc else 0))
        
        mapping_id = cursor.lastrowid
        conn.commit()
        
        dest_info = webhook_url[:50] if destination_type == 'webhook' else destination_channel_id
        print(f"[DATABASE] ✓ Added channel mapping: {source_channel_id} -> {dest_info} (type={destination_type}, forward={forward_enabled})")
        
        return {
            'success': True,
            'id': mapping_id,
            'message': 'Channel mapping added successfully'
        }
    except sqlite3.IntegrityError:
        return {
            'success': False,
            'error': 'This mapping already exists'
        }
    except Exception as e:
        print(f"[DATABASE] Error adding channel mapping: {e}")
        conn.rollback()
        return {
            'success': False,
            'error': str(e)
        }


def update_channel_mapping(mapping_id: int, source_channel_id: str = None, 
                           webhook_url: str = None,
                           source_channel_name: str = None, 
                           webhook_name: str = None,
                           is_active: bool = None,
                           forward_enabled: bool = None,
                           execute_on_source: bool = None,
                           format_as_bto_stc: bool = None,
                           destination_type: str = None,
                           destination_channel_id: str = None,
                           destination_channel_name: str = None) -> Dict[str, Any]:
    """Update an existing channel mapping"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        updates = []
        params = []
        
        if source_channel_id is not None:
            updates.append('source_channel_id = ?')
            params.append(source_channel_id.strip())
        if webhook_url is not None:
            updates.append('webhook_url = ?')
            params.append(webhook_url.strip())
        if source_channel_name is not None:
            updates.append('source_channel_name = ?')
            params.append(source_channel_name.strip())
        if webhook_name is not None:
            updates.append('webhook_name = ?')
            params.append(webhook_name.strip())
        if is_active is not None:
            updates.append('is_active = ?')
            params.append(1 if is_active else 0)
        if forward_enabled is not None:
            updates.append('forward_enabled = ?')
            params.append(1 if forward_enabled else 0)
        if execute_on_source is not None:
            updates.append('execute_on_source = ?')
            params.append(1 if execute_on_source else 0)
        if format_as_bto_stc is not None:
            updates.append('format_as_bto_stc = ?')
            params.append(1 if format_as_bto_stc else 0)
        if destination_type is not None:
            updates.append('destination_type = ?')
            params.append(destination_type.strip())
        if destination_channel_id is not None:
            updates.append('destination_channel_id = ?')
            params.append(destination_channel_id.strip())
        if destination_channel_name is not None:
            updates.append('destination_channel_name = ?')
            params.append(destination_channel_name.strip())
        
        if not updates:
            return {'success': False, 'error': 'No fields to update'}
        
        updates.append('updated_at = CURRENT_TIMESTAMP')
        params.append(mapping_id)
        
        cursor.execute(f'''
            UPDATE channel_mappings
            SET {', '.join(updates)}
            WHERE id = ?
        ''', params)
        
        conn.commit()
        print(f"[DATABASE] ✓ Updated channel mapping ID {mapping_id}")
        
        return {'success': True, 'message': 'Channel mapping updated successfully'}
    except Exception as e:
        print(f"[DATABASE] Error updating channel mapping: {e}")
        conn.rollback()
        return {'success': False, 'error': str(e)}


def delete_channel_mapping(mapping_id: int) -> Dict[str, Any]:
    """Delete a channel mapping"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('DELETE FROM channel_mappings WHERE id = ?', (mapping_id,))
        
        if cursor.rowcount == 0:
            return {'success': False, 'error': 'Mapping not found'}
        
        conn.commit()
        print(f"[DATABASE] ✓ Deleted channel mapping ID {mapping_id}")
        
        return {'success': True, 'message': 'Channel mapping deleted successfully'}
    except Exception as e:
        print(f"[DATABASE] Error deleting channel mapping: {e}")
        conn.rollback()
        return {'success': False, 'error': str(e)}


def get_webhook_for_source(source_channel_id: str) -> Dict[str, str]:
    """Get the webhook URL and name for a given source channel"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        migrate_channel_mappings_to_webhook()
        cursor.execute('''
            SELECT webhook_url, webhook_name
            FROM channel_mappings
            WHERE source_channel_id = ? AND is_active = 1
            LIMIT 1
        ''', (source_channel_id,))
        
        row = cursor.fetchone()
        if row:
            return {'webhook_url': row['webhook_url'], 'webhook_name': row['webhook_name']}
        return None
    except Exception as e:
        print(f"[DATABASE] Error getting webhook for source: {e}")
        return None


def get_all_active_webhook_mappings() -> List[Dict[str, str]]:
    """Get all active webhook URLs from channel_mappings for Trade Monitor broadcasting.
    
    Also fetches bot_name from webhook_channels table if available.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        init_channel_mappings_table()
        cursor.execute('''
            SELECT DISTINCT cm.webhook_url, cm.webhook_name,
                   wc.name as bot_name
            FROM channel_mappings cm
            LEFT JOIN webhook_channels wc ON cm.webhook_url = wc.webhook_url
            WHERE cm.is_active = 1 AND cm.webhook_url IS NOT NULL AND cm.webhook_url != ''
        ''')
        
        rows = cursor.fetchall()
        result = []
        for row in rows:
            webhook_name = row['webhook_name'] or 'Unnamed'
            bot_name = row['bot_name'] or webhook_name or 'BotifyTrades'
            result.append({
                'webhook_url': row['webhook_url'],
                'webhook_name': webhook_name,
                'bot_name': bot_name
            })
        return result
    except Exception as e:
        print(f"[DATABASE] Error getting active webhook mappings: {e}")
        return []


# ============ WAITLIST MANAGEMENT ============

def add_to_waitlist(email: str, name: str = None, source: str = 'docs_page', referral_code: str = None) -> Dict[str, Any]:
    """
    Add a new user to the waitlist with automatic queue position.
    Returns dict with success status and queue position.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Get next queue position
        cursor.execute('SELECT COALESCE(MAX(queue_position), 0) + 1 FROM waitlist')
        queue_position = cursor.fetchone()[0]
        
        # Check for referral
        referred_by = None
        if referral_code:
            cursor.execute('SELECT id FROM waitlist WHERE referral_code = ?', (referral_code,))
            referrer = cursor.fetchone()
            if referrer:
                referred_by = referrer['id']
        
        # Generate unique referral code for this user
        import hashlib
        user_referral_code = hashlib.md5(f"{email}{datetime.now().isoformat()}".encode()).hexdigest()[:8].upper()
        
        cursor.execute('''
            INSERT INTO waitlist (email, name, source, queue_position, referral_code, referred_by)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (email.lower().strip(), name, source, queue_position, user_referral_code, referred_by))
        
        conn.commit()
        
        return {
            'success': True,
            'queue_position': queue_position,
            'referral_code': user_referral_code,
            'message': f'You are #{queue_position} on the waitlist!'
        }
    except sqlite3.IntegrityError:
        # Email already exists - get their position
        cursor.execute('SELECT queue_position, referral_code FROM waitlist WHERE email = ?', (email.lower().strip(),))
        existing = cursor.fetchone()
        if existing:
            return {
                'success': False,
                'already_registered': True,
                'queue_position': existing['queue_position'],
                'referral_code': existing['referral_code'],
                'message': f'You are already on the waitlist at position #{existing["queue_position"]}!'
            }
        return {'success': False, 'error': 'Email already registered'}
    except Exception as e:
        print(f"[DATABASE] Error adding to waitlist: {e}")
        return {'success': False, 'error': str(e)}


def get_waitlist(status: str = None, limit: int = 100) -> List[Dict]:
    """Get waitlist entries, optionally filtered by status."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        if status:
            cursor.execute('''
                SELECT w.*, 
                    (SELECT COUNT(*) FROM waitlist w2 WHERE w2.referred_by = w.referral_code) as referral_count
                FROM waitlist w
                WHERE w.status = ? 
                ORDER BY w.queue_position ASC 
                LIMIT ?
            ''', (status, limit))
        else:
            cursor.execute('''
                SELECT w.*, 
                    (SELECT COUNT(*) FROM waitlist w2 WHERE w2.referred_by = w.referral_code) as referral_count
                FROM waitlist w
                ORDER BY w.queue_position ASC 
                LIMIT ?
            ''', (limit,))
        
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"[DATABASE] Error getting waitlist: {e}")
        return []


def get_waitlist_stats() -> Dict[str, Any]:
    """Get waitlist statistics."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT COUNT(*) FROM waitlist')
        total = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM waitlist WHERE status = 'pending'")
        pending = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM waitlist WHERE status = 'invited'")
        invited = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM waitlist WHERE status = 'registered'")
        registered = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM waitlist WHERE status = 'notified'")
        notified = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM waitlist WHERE status = 'rejected'")
        rejected = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM waitlist WHERE referred_by IS NOT NULL")
        referred_count = cursor.fetchone()[0]
        
        return {
            'total': total,
            'pending': pending,
            'invited': invited,
            'registered': registered,
            'notified': notified,
            'rejected': rejected,
            'referred_count': referred_count
        }
    except Exception as e:
        print(f"[DATABASE] Error getting waitlist stats: {e}")
        return {'total': 0, 'pending': 0, 'invited': 0, 'registered': 0, 'notified': 0, 'rejected': 0, 'referred_count': 0}


def update_waitlist_status(waitlist_id: int, status: str) -> bool:
    """Update a waitlist entry's status."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        now = datetime.now().isoformat()
        
        if status == 'invited':
            cursor.execute('''
                UPDATE waitlist SET status = ?, invited_at = ? WHERE id = ?
            ''', (status, now, waitlist_id))
        elif status == 'registered':
            cursor.execute('''
                UPDATE waitlist SET status = ?, registered_at = ? WHERE id = ?
            ''', (status, now, waitlist_id))
        else:
            cursor.execute('''
                UPDATE waitlist SET status = ? WHERE id = ?
            ''', (status, waitlist_id))
        
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"[DATABASE] Error updating waitlist status: {e}")
        return False


def delete_from_waitlist(waitlist_id: int) -> bool:
    """Delete a waitlist entry."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('DELETE FROM waitlist WHERE id = ?', (waitlist_id,))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"[DATABASE] Error deleting from waitlist: {e}")
        return False


# ============ END USER MANAGEMENT (Customer Portal) ============

def init_end_user_tables():
    """Initialize end user and subscription tables."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # End users table (customers, not admin users)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS end_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            first_name TEXT,
            last_name TEXT,
            created_at TEXT NOT NULL,
            last_login TEXT,
            status TEXT DEFAULT 'active'
        )
    ''')
    
    # User subscriptions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan_name TEXT DEFAULT 'Free Trial',
            license_key TEXT,
            license_type TEXT DEFAULT 'trial',
            status TEXT DEFAULT 'active',
            expires_at TEXT,
            machine_id TEXT,
            machine_bound INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            FOREIGN KEY (user_id) REFERENCES end_users(id)
        )
    ''')
    
    conn.commit()


def create_end_user(username: str, email: str, password: str, first_name: str = '', last_name: str = '') -> Optional[int]:
    """Create a new end user account. Returns user ID or None on failure."""
    import hashlib
    import secrets
    
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Initialize tables if needed
        init_end_user_tables()
        
        # Generate salt and hash password
        salt = secrets.token_hex(32)
        password_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        ).hex()
        
        now = datetime.now().isoformat()
        
        cursor.execute('''
            INSERT INTO end_users (username, email, password_hash, password_salt, first_name, last_name, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (username, email, password_hash, salt, first_name, last_name, now))
        
        user_id = cursor.lastrowid
        
        # Create default subscription (free trial, 14 days)
        import secrets as sec
        license_key = f"BT-TRIAL-{sec.token_hex(8).upper()}"
        expires_at = (datetime.now() + timedelta(days=14)).isoformat()
        
        cursor.execute('''
            INSERT INTO user_subscriptions (user_id, plan_name, license_key, license_type, status, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, 'Free Trial', license_key, 'trial', 'active', expires_at, now))
        
        conn.commit()
        print(f"[DATABASE] Created end user: {username} (ID: {user_id})")
        return user_id
        
    except sqlite3.IntegrityError as e:
        print(f"[DATABASE] End user already exists: {e}")
        return None
    except Exception as e:
        print(f"[DATABASE] Error creating end user: {e}")
        return None


def get_end_user_by_email(email: str) -> Optional[Dict]:
    """Get end user by email address."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        init_end_user_tables()
        cursor.execute('SELECT * FROM end_users WHERE email = ?', (email.lower(),))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DATABASE] Error getting end user by email: {e}")
        return None


def get_end_user_by_username(username: str) -> Optional[Dict]:
    """Get end user by username."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        init_end_user_tables()
        cursor.execute('SELECT * FROM end_users WHERE username = ?', (username.lower(),))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DATABASE] Error getting end user by username: {e}")
        return None


def get_end_user_by_id(user_id: int) -> Optional[Dict]:
    """Get end user by ID."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        init_end_user_tables()
        cursor.execute('SELECT * FROM end_users WHERE id = ?', (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DATABASE] Error getting end user by ID: {e}")
        return None


def verify_end_user_password(user_id: int, password: str) -> bool:
    """Verify end user password."""
    import hashlib
    
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT password_hash, password_salt FROM end_users WHERE id = ?', (user_id,))
        row = cursor.fetchone()
        
        if not row:
            return False
        
        stored_hash = row['password_hash']
        salt = row['password_salt']
        
        # Hash provided password with same salt
        test_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        ).hex()
        
        if test_hash == stored_hash:
            # Update last login
            cursor.execute(
                'UPDATE end_users SET last_login = ? WHERE id = ?',
                (datetime.now().isoformat(), user_id)
            )
            conn.commit()
            return True
        
        return False
        
    except Exception as e:
        print(f"[DATABASE] Error verifying end user password: {e}")
        return False


def get_user_subscription(user_id: int) -> Dict:
    """Get user subscription details."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        init_end_user_tables()
        cursor.execute('''
            SELECT * FROM user_subscriptions WHERE user_id = ? ORDER BY id DESC LIMIT 1
        ''', (user_id,))
        row = cursor.fetchone()
        
        if row:
            sub = dict(row)
            
            # Calculate days remaining
            if sub.get('expires_at'):
                try:
                    expires = datetime.fromisoformat(sub['expires_at'])
                    now = datetime.now()
                    days_remaining = (expires - now).days
                    sub['days_remaining'] = max(0, days_remaining)
                    sub['expiry_date'] = expires.strftime('%B %d, %Y')
                    
                    # Update status if expired
                    if days_remaining < 0 and sub['status'] == 'active':
                        sub['status'] = 'expired'
                except:
                    sub['days_remaining'] = 0
                    sub['expiry_date'] = 'N/A'
            else:
                sub['days_remaining'] = None
                sub['expiry_date'] = 'N/A'
            
            return sub
        
        # Return default subscription info if none exists
        return {
            'plan_name': 'No Plan',
            'license_key': None,
            'license_type': None,
            'status': 'inactive',
            'expires_at': None,
            'expiry_date': 'N/A',
            'days_remaining': 0,
            'machine_bound': False
        }
        
    except Exception as e:
        print(f"[DATABASE] Error getting user subscription: {e}")
        return {
            'plan_name': 'Error',
            'license_key': None,
            'license_type': None,
            'status': 'error',
            'expires_at': None,
            'expiry_date': 'N/A',
            'days_remaining': 0,
            'machine_bound': False
        }


def update_user_subscription(user_id: int, **kwargs) -> bool:
    """Update user subscription fields."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Build update query dynamically
        allowed_fields = ['plan_name', 'license_key', 'license_type', 'status', 'expires_at', 'machine_id', 'machine_bound']
        updates = []
        values = []
        
        for field in allowed_fields:
            if field in kwargs:
                updates.append(f"{field} = ?")
                values.append(kwargs[field])
        
        if not updates:
            return False
        
        updates.append("updated_at = ?")
        values.append(datetime.now().isoformat())
        values.append(user_id)
        
        query = f"UPDATE user_subscriptions SET {', '.join(updates)} WHERE user_id = ?"
        cursor.execute(query, values)
        conn.commit()
        
        return cursor.rowcount > 0
        
    except Exception as e:
        print(f"[DATABASE] Error updating user subscription: {e}")
        return False


# ==================== ERROR LOGGING & MONITORING ====================

def log_error(error_type: str, error_message: str, component: str = None, 
              context: str = None, stack_trace: str = None, 
              severity: str = 'error', error_code: str = None) -> int:
    """
    Log an error to the database for AI assistant context awareness.
    Returns the error log ID.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Check if similar error exists (same type and message within last hour)
        cursor.execute('''
            SELECT id, occurrence_count FROM error_logs 
            WHERE error_type = ? AND error_message = ? 
            AND last_seen > datetime('now', '-1 hour')
            AND resolved = 0
        ''', (error_type, error_message))
        
        existing = cursor.fetchone()
        
        if existing:
            # Update existing error with new occurrence
            cursor.execute('''
                UPDATE error_logs 
                SET occurrence_count = occurrence_count + 1,
                    last_seen = CURRENT_TIMESTAMP,
                    user_notified = 0
                WHERE id = ?
            ''', (existing['id'],))
            conn.commit()
            return existing['id']
        else:
            # Insert new error
            cursor.execute('''
                INSERT INTO error_logs 
                (error_type, error_code, error_message, component, context, stack_trace, severity)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (error_type, error_code, error_message, component, context, stack_trace, severity))
            conn.commit()
            return cursor.lastrowid
            
    except Exception as e:
        print(f"[DATABASE] Error logging error: {e}")
        return -1


def get_recent_errors(limit: int = 10, include_resolved: bool = False, 
                      severity: str = None, hours: int = 24) -> List[Dict]:
    """Get recent errors from the log."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        query = '''
            SELECT * FROM error_logs 
            WHERE last_seen > datetime('now', ? || ' hours')
        '''
        params = [f'-{hours}']
        
        if not include_resolved:
            query += ' AND resolved = 0'
        
        if severity:
            query += ' AND severity = ?'
            params.append(severity)
        
        query += ' ORDER BY last_seen DESC LIMIT ?'
        params.append(limit)
        
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
        
    except Exception as e:
        print(f"[DATABASE] Error getting recent errors: {e}")
        return []


def get_unnotified_errors() -> List[Dict]:
    """Get errors that the user hasn't been notified about yet."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT * FROM error_logs 
            WHERE user_notified = 0 AND resolved = 0
            ORDER BY severity DESC, last_seen DESC
        ''')
        return [dict(row) for row in cursor.fetchall()]
        
    except Exception as e:
        print(f"[DATABASE] Error getting unnotified errors: {e}")
        return []


def mark_errors_notified(error_ids: List[int]) -> bool:
    """Mark errors as notified to the user."""
    if not error_ids:
        return True
        
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        placeholders = ','.join(['?' for _ in error_ids])
        cursor.execute(f'''
            UPDATE error_logs SET user_notified = 1 WHERE id IN ({placeholders})
        ''', error_ids)
        conn.commit()
        return True
        
    except Exception as e:
        print(f"[DATABASE] Error marking errors notified: {e}")
        return False


def resolve_error(error_id: int, resolution_notes: str = None) -> bool:
    """Mark an error as resolved."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE error_logs 
            SET resolved = 1, resolution_notes = ?
            WHERE id = ?
        ''', (resolution_notes, error_id))
        conn.commit()
        return cursor.rowcount > 0
        
    except Exception as e:
        print(f"[DATABASE] Error resolving error: {e}")
        return False


def get_error_stats(hours: int = 24) -> Dict:
    """Get error statistics for the dashboard."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Total unresolved errors
        cursor.execute('''
            SELECT COUNT(*) as total, 
                   SUM(CASE WHEN severity = 'critical' THEN 1 ELSE 0 END) as critical,
                   SUM(CASE WHEN severity = 'error' THEN 1 ELSE 0 END) as errors,
                   SUM(CASE WHEN severity = 'warning' THEN 1 ELSE 0 END) as warnings
            FROM error_logs 
            WHERE resolved = 0 AND last_seen > datetime('now', ? || ' hours')
        ''', (f'-{hours}',))
        row = cursor.fetchone()
        
        return {
            'total': row['total'] or 0,
            'critical': row['critical'] or 0,
            'errors': row['errors'] or 0,
            'warnings': row['warnings'] or 0
        }
        
    except Exception as e:
        print(f"[DATABASE] Error getting error stats: {e}")
        return {'total': 0, 'critical': 0, 'errors': 0, 'warnings': 0}


def get_frequent_errors(limit: int = 5, days: int = 7) -> List[Dict]:
    """Get most frequent errors in the past N days."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT error_type, error_message, component, 
                   SUM(occurrence_count) as total_occurrences,
                   MAX(last_seen) as last_occurrence,
                   severity
            FROM error_logs 
            WHERE first_seen > datetime('now', ? || ' days')
            GROUP BY error_type, error_message
            ORDER BY total_occurrences DESC
            LIMIT ?
        ''', (f'-{days}', limit))
        
        return [dict(row) for row in cursor.fetchall()]
        
    except Exception as e:
        print(f"[DATABASE] Error getting frequent errors: {e}")
        return []


def find_known_issue_solution(error_message: str) -> Optional[Dict]:
    """Find a known issue solution that matches the error message."""
    import re
    
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT * FROM known_issues WHERE auto_detect = 1')
        issues = cursor.fetchall()
        
        for issue in issues:
            pattern = issue['error_pattern']
            if re.search(pattern, error_message, re.IGNORECASE):
                return dict(issue)
        
        return None
        
    except Exception as e:
        print(f"[DATABASE] Error finding known issue: {e}")
        return None


def get_all_known_issues() -> List[Dict]:
    """Get all known issues for reference."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT * FROM known_issues ORDER BY category, issue_title')
        return [dict(row) for row in cursor.fetchall()]
        
    except Exception as e:
        print(f"[DATABASE] Error getting known issues: {e}")
        return []


def clear_old_errors(days: int = 30) -> int:
    """Clear resolved errors older than N days. Returns count deleted."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            DELETE FROM error_logs 
            WHERE resolved = 1 AND last_seen < datetime('now', ? || ' days')
        ''', (f'-{days}',))
        conn.commit()
        return cursor.rowcount
        
    except Exception as e:
        print(f"[DATABASE] Error clearing old errors: {e}")
        return 0


# ==================== SERVER-SIDE LICENSE MANAGEMENT ====================
# These functions are used when running as a license server (LICENSE_SERVER_MODE=true)

def create_server_license(license_key: str, license_type: str, expires_at: str = None,
                          customer_id: str = None, customer_email: str = None,
                          customer_name: str = None, max_devices: int = 1,
                          notes: str = None) -> Optional[int]:
    """Create a new license in the server database."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO server_licenses 
            (license_key, license_type, customer_id, customer_email, customer_name, 
             max_devices, expires_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (license_key, license_type, customer_id, customer_email, customer_name,
              max_devices, expires_at, notes))
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None
    except Exception as e:
        print(f"[DATABASE] Error creating license: {e}")
        return None


def get_server_license(license_key: str) -> Optional[Dict]:
    """Get license details by key."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT * FROM server_licenses WHERE license_key = ?', (license_key,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DATABASE] Error getting license: {e}")
        return None


def get_server_license_by_machine(machine_id: str) -> Optional[Dict]:
    """Get license bound to a specific machine."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT sl.* FROM server_licenses sl
            JOIN server_machines sm ON sl.id = sm.license_id
            WHERE sm.machine_id = ? AND sl.status = 'active' AND sm.is_active = 1
            ORDER BY sl.expires_at DESC
            LIMIT 1
        ''', (machine_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DATABASE] Error getting license by machine: {e}")
        return None


def activate_server_license(license_key: str, machine_id: str, machine_info: str = None,
                            ip_address: str = None) -> Dict:
    """Activate a license for a specific machine."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Get license
        cursor.execute('SELECT * FROM server_licenses WHERE license_key = ?', (license_key,))
        license_row = cursor.fetchone()
        
        if not license_row:
            return {'success': False, 'error': 'License key not found'}
        
        license_data = dict(license_row)
        
        # Check if license is active
        if license_data['status'] != 'active':
            return {'success': False, 'error': f"License is {license_data['status']}"}
        
        # Check if expired
        if license_data['expires_at']:
            from datetime import datetime
            expires = datetime.fromisoformat(license_data['expires_at'].replace('Z', '+00:00')) if 'T' in license_data['expires_at'] else datetime.strptime(license_data['expires_at'], '%Y-%m-%d %H:%M:%S')
            if expires < datetime.now():
                cursor.execute('UPDATE server_licenses SET status = ? WHERE id = ?', ('expired', license_data['id']))
                conn.commit()
                return {'success': False, 'error': 'License has expired'}
        
        # Check if machine is already bound
        cursor.execute('''
            SELECT * FROM server_machines WHERE license_id = ? AND machine_id = ?
        ''', (license_data['id'], machine_id))
        existing_machine = cursor.fetchone()
        
        if existing_machine:
            was_inactive = existing_machine['is_active'] == 0
            
            # ALWAYS set is_active=1 when activating (fixes reactivation after reset)
            cursor.execute('''
                UPDATE server_machines 
                SET is_active = 1, last_seen_at = CURRENT_TIMESTAMP, last_seen_ip = ?, machine_info = COALESCE(?, machine_info)
                WHERE id = ?
            ''', (ip_address, machine_info, existing_machine['id']))
            
            # Recalculate devices_used from actual active machine count
            cursor.execute('SELECT COUNT(*) as count FROM server_machines WHERE license_id = ? AND is_active = 1', 
                          (license_data['id'],))
            active_count = cursor.fetchone()['count']
            
            cursor.execute('''
                UPDATE server_licenses 
                SET devices_used = ?, last_validated_at = CURRENT_TIMESTAMP, last_validated_ip = ?
                WHERE id = ?
            ''', (active_count, ip_address, license_data['id']))
            conn.commit()
            
            print(f"[LICENSE-DB] Machine {machine_id[:8]} reactivated (was_inactive={was_inactive}), devices_used={active_count}")
            
            return {
                'success': True,
                'message': 'License activated' if was_inactive else 'License validated',
                'license_type': license_data['license_type'],
                'expires_at': license_data['expires_at'],
                'customer_id': license_data['customer_id'],
                'reactivated': was_inactive
            }
        
        # Check device limit
        cursor.execute('SELECT COUNT(*) as count FROM server_machines WHERE license_id = ? AND is_active = 1', 
                       (license_data['id'],))
        device_count = cursor.fetchone()['count']
        
        if device_count >= license_data['max_devices']:
            return {'success': False, 'error': f"Device limit reached ({license_data['max_devices']}). Deactivate another device first."}
        
        # Add new machine with is_active=1
        cursor.execute('''
            INSERT INTO server_machines (license_id, machine_id, machine_info, first_seen_ip, last_seen_ip, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
        ''', (license_data['id'], machine_id, machine_info, ip_address, ip_address))
        
        # Recalculate devices_used from actual active count (atomic)
        cursor.execute('SELECT COUNT(*) as count FROM server_machines WHERE license_id = ? AND is_active = 1', 
                      (license_data['id'],))
        active_count = cursor.fetchone()['count']
        
        cursor.execute('''
            UPDATE server_licenses 
            SET devices_used = ?, 
                activated_at = COALESCE(activated_at, CURRENT_TIMESTAMP),
                last_validated_at = CURRENT_TIMESTAMP,
                last_validated_ip = ?
            WHERE id = ?
        ''', (active_count, ip_address, license_data['id']))
        
        conn.commit()
        
        print(f"[LICENSE-DB] New machine {machine_id[:8]} activated, devices_used={active_count}")
        
        return {
            'success': True,
            'message': 'License activated successfully',
            'license_type': license_data['license_type'],
            'expires_at': license_data['expires_at'],
            'customer_id': license_data['customer_id']
        }
        
    except Exception as e:
        print(f"[DATABASE] Error activating license: {e}")
        return {'success': False, 'error': str(e)}


def validate_server_license(license_key: str, machine_id: str, ip_address: str = None) -> Dict:
    """Validate a license for a specific machine."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Get license
        cursor.execute('SELECT * FROM server_licenses WHERE license_key = ?', (license_key,))
        license_row = cursor.fetchone()
        
        if not license_row:
            log_license_action(license_key, machine_id, 'validate', 'failed', ip_address, error='License not found')
            return {'is_valid': False, 'error': 'License key not found'}
        
        license_data = dict(license_row)
        
        # Check status
        if license_data['status'] != 'active':
            log_license_action(license_key, machine_id, 'validate', 'failed', ip_address, error=f"Status: {license_data['status']}")
            return {'is_valid': False, 'error': f"License is {license_data['status']}"}
        
        # Check expiry
        if license_data['expires_at']:
            from datetime import datetime
            try:
                expires = datetime.fromisoformat(license_data['expires_at'].replace('Z', '+00:00')) if 'T' in license_data['expires_at'] else datetime.strptime(license_data['expires_at'], '%Y-%m-%d %H:%M:%S')
                now = datetime.now()
                if expires < now:
                    cursor.execute('UPDATE server_licenses SET status = ? WHERE id = ?', ('expired', license_data['id']))
                    conn.commit()
                    log_license_action(license_key, machine_id, 'validate', 'failed', ip_address, error='Expired')
                    return {'is_valid': False, 'error': 'License has expired'}
                days_remaining = (expires - now).days
            except:
                days_remaining = 999
        else:
            days_remaining = 999  # Lifetime license
        
        # Check machine binding
        cursor.execute('''
            SELECT * FROM server_machines WHERE license_id = ? AND machine_id = ? AND is_active = 1
        ''', (license_data['id'], machine_id))
        machine_row = cursor.fetchone()
        
        if not machine_row:
            log_license_action(license_key, machine_id, 'validate', 'failed', ip_address, error='Machine not bound')
            return {'is_valid': False, 'error': 'License not activated on this machine'}
        
        # Update last validated
        cursor.execute('''
            UPDATE server_machines SET last_seen_at = CURRENT_TIMESTAMP, last_seen_ip = ?
            WHERE id = ?
        ''', (ip_address, machine_row['id']))
        cursor.execute('''
            UPDATE server_licenses SET last_validated_at = CURRENT_TIMESTAMP, last_validated_ip = ?
            WHERE id = ?
        ''', (ip_address, license_data['id']))
        conn.commit()
        
        log_license_action(license_key, machine_id, 'validate', 'success', ip_address)
        
        return {
            'is_valid': True,
            'license_type': license_data['license_type'],
            'customer_id': license_data['customer_id'],
            'expires': license_data['expires_at'],
            'days_remaining': days_remaining
        }
        
    except Exception as e:
        print(f"[DATABASE] Error validating license: {e}")
        return {'is_valid': False, 'error': str(e)}


def request_server_trial(machine_id: str, ip_address: str = None, user_agent: str = None) -> Dict:
    """Request a trial license for a machine (one per machine)."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Check if machine already has a trial
        cursor.execute('SELECT * FROM server_trials WHERE machine_id = ?', (machine_id,))
        existing_trial = cursor.fetchone()
        
        if existing_trial:
            log_license_action(None, machine_id, 'trial_request', 'blocked', ip_address, error='Trial already used')
            return {
                'success': False,
                'error': 'A trial has already been used on this machine. Please purchase a license.'
            }
        
        # Generate trial license key
        import secrets
        trial_key = f"TRIAL-{secrets.token_hex(8).upper()}"
        
        # Calculate expiry (7 days)
        from datetime import datetime, timedelta
        expires_at = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
        
        # Create trial record
        cursor.execute('''
            INSERT INTO server_trials (machine_id, license_key, first_ip, user_agent, expires_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (machine_id, trial_key, ip_address, user_agent, expires_at))
        
        # Also create a license record for consistency
        cursor.execute('''
            INSERT INTO server_licenses 
            (license_key, license_type, machine_id, max_devices, expires_at, activated_at, status)
            VALUES (?, 'trial', ?, 1, ?, CURRENT_TIMESTAMP, 'active')
        ''', (trial_key, machine_id, expires_at))
        license_id = cursor.lastrowid
        
        # Bind machine
        cursor.execute('''
            INSERT INTO server_machines (license_id, machine_id, first_seen_ip, last_seen_ip)
            VALUES (?, ?, ?, ?)
        ''', (license_id, machine_id, ip_address, ip_address))
        
        conn.commit()
        
        log_license_action(trial_key, machine_id, 'trial_request', 'success', ip_address)
        
        return {
            'success': True,
            'license_key': trial_key,
            'expires_at': expires_at,
            'days_remaining': 7,
            'message': 'Trial activated! You have 7 days to try BotifyTrades.'
        }
        
    except Exception as e:
        print(f"[DATABASE] Error creating trial: {e}")
        return {'success': False, 'error': str(e)}


def revoke_server_license(license_key: str, reason: str = None) -> bool:
    """Revoke a license."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE server_licenses SET status = 'revoked', notes = COALESCE(notes || ' | ', '') || ?
            WHERE license_key = ?
        ''', (f"Revoked: {reason}" if reason else "Revoked by admin", license_key))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"[DATABASE] Error revoking license: {e}")
        return False


def deactivate_machine(license_key: str, machine_id: str) -> bool:
    """Deactivate a machine from a license (to free up device slot)."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT id FROM server_licenses WHERE license_key = ?', (license_key,))
        license_row = cursor.fetchone()
        
        if not license_row:
            return False
        
        cursor.execute('''
            UPDATE server_machines SET is_active = 0 
            WHERE license_id = ? AND machine_id = ?
        ''', (license_row['id'], machine_id))
        
        if cursor.rowcount > 0:
            cursor.execute('''
                UPDATE server_licenses SET devices_used = MAX(0, devices_used - 1)
                WHERE id = ?
            ''', (license_row['id'],))
        
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"[DATABASE] Error deactivating machine: {e}")
        return False


def get_all_server_licenses(include_expired: bool = False) -> List[Dict]:
    """Get all licenses for admin view."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        if include_expired:
            cursor.execute('SELECT * FROM server_licenses ORDER BY created_at DESC')
        else:
            cursor.execute("SELECT * FROM server_licenses WHERE status = 'active' ORDER BY created_at DESC")
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"[DATABASE] Error getting licenses: {e}")
        return []


def get_all_server_trials() -> List[Dict]:
    """Get all trial records for admin view."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT * FROM server_trials ORDER BY created_at DESC')
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"[DATABASE] Error getting trials: {e}")
        return []


def get_license_machines(license_key: str) -> List[Dict]:
    """Get all machines bound to a license."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT sm.* FROM server_machines sm
            JOIN server_licenses sl ON sm.license_id = sl.id
            WHERE sl.license_key = ?
            ORDER BY sm.last_seen_at DESC
        ''', (license_key,))
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"[DATABASE] Error getting license machines: {e}")
        return []


def update_server_license(license_key: str, **kwargs) -> bool:
    """Update license fields dynamically."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        allowed_fields = ['customer_name', 'customer_email', 'max_devices', 'notes', 'expires_at', 'status']
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
        
        if not updates:
            return False
        
        set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [license_key]
        
        cursor.execute(f'''
            UPDATE server_licenses SET {set_clause} WHERE license_key = ?
        ''', values)
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"[DATABASE] Error updating license: {e}")
        return False


def reset_license_devices(license_key: str) -> bool:
    """Reset all device bindings for a license (free up all device slots)."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT id FROM server_licenses WHERE license_key = ?', (license_key,))
        license_row = cursor.fetchone()
        
        if not license_row:
            return False
        
        cursor.execute('''
            UPDATE server_machines SET is_active = 0 
            WHERE license_id = ?
        ''', (license_row['id'],))
        
        cursor.execute('''
            UPDATE server_licenses SET devices_used = 0
            WHERE id = ?
        ''', (license_row['id'],))
        
        conn.commit()
        return True
    except Exception as e:
        print(f"[DATABASE] Error resetting license devices: {e}")
        return False


def get_license_validations(license_key: str, limit: int = 20) -> List[Dict]:
    """Get recent validation logs for a license."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT * FROM license_validation_log 
            WHERE license_key = ?
            ORDER BY created_at DESC
            LIMIT ?
        ''', (license_key, limit))
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"[DATABASE] Error getting license validations: {e}")
        return []


def log_license_action(license_key: str, machine_id: str, action: str, result: str,
                       ip_address: str = None, user_agent: str = None, error: str = None):
    """Log a license validation action."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO license_validation_log 
            (license_key, machine_id, action, result, ip_address, user_agent, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (license_key, machine_id, action, result, ip_address, user_agent, error))
        conn.commit()
    except Exception as e:
        print(f"[DATABASE] Error logging license action: {e}")


# ==================== CLIENT-SIDE LICENSE STORAGE FUNCTIONS ====================

def save_local_license(license_key: str, machine_id: str, license_data: Dict) -> bool:
    """
    Save activated license to local database for persistence across restarts.
    This replaces any existing license (single-row table).
    
    Args:
        license_key: The activated license key
        machine_id: The machine ID this license is bound to
        license_data: Dict containing license_type, days_remaining, expires_at, signed_token
        
    Returns:
        True if saved successfully, False otherwise
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        now = datetime.now().isoformat()
        
        cursor.execute('''
            INSERT OR REPLACE INTO local_license 
            (id, license_key, machine_id, license_type, days_remaining, expires_at, 
             signed_token, last_validated_at, activated_at, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, 
                    COALESCE((SELECT activated_at FROM local_license WHERE id = 1), ?), ?)
        ''', (
            license_key,
            machine_id,
            license_data.get('license_type', 'subscription'),
            license_data.get('days_remaining', 0),
            license_data.get('expires_at') or license_data.get('expires'),
            license_data.get('signed_token'),
            now,
            now,
            now
        ))
        conn.commit()
        print(f"[DATABASE] ✓ License saved to database: {license_key[:12]}...")
        return True
    except Exception as e:
        print(f"[DATABASE] Error saving local license: {e}")
        return False


def get_local_license() -> Optional[Dict]:
    """
    Get the locally stored license from database.
    
    Returns:
        Dict with license data or None if no license stored
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT * FROM local_license WHERE id = 1')
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    except Exception as e:
        print(f"[DATABASE] Error loading local license: {e}")
        return None


def clear_local_license() -> bool:
    """Clear the locally stored license (for logout/deactivation)."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('DELETE FROM local_license WHERE id = 1')
        conn.commit()
        print("[DATABASE] ✓ Local license cleared")
        return True
    except Exception as e:
        print(f"[DATABASE] Error clearing local license: {e}")
        return False


def update_local_license_validation(days_remaining: int = None, signed_token: str = None) -> bool:
    """
    Update the last_validated_at timestamp and optionally days_remaining for the local license.
    Called after successful server validation to keep cache fresh.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        now = datetime.now().isoformat()
        
        if days_remaining is not None and signed_token is not None:
            cursor.execute('''
                UPDATE local_license 
                SET last_validated_at = ?, days_remaining = ?, signed_token = ?, updated_at = ?
                WHERE id = 1
            ''', (now, days_remaining, signed_token, now))
        elif days_remaining is not None:
            cursor.execute('''
                UPDATE local_license 
                SET last_validated_at = ?, days_remaining = ?, updated_at = ?
                WHERE id = 1
            ''', (now, days_remaining, now))
        else:
            cursor.execute('''
                UPDATE local_license 
                SET last_validated_at = ?, updated_at = ?
                WHERE id = 1
            ''', (now, now))
        
        conn.commit()
        return True
    except Exception as e:
        print(f"[DATABASE] Error updating local license validation: {e}")
        return False


def get_license_stats() -> Dict:
    """Get license statistics for admin dashboard."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        stats = {}
        
        # Total licenses by type
        cursor.execute('''
            SELECT license_type, COUNT(*) as count FROM server_licenses GROUP BY license_type
        ''')
        stats['by_type'] = {row['license_type']: row['count'] for row in cursor.fetchall()}
        
        # Total licenses by status
        cursor.execute('''
            SELECT status, COUNT(*) as count FROM server_licenses GROUP BY status
        ''')
        stats['by_status'] = {row['status']: row['count'] for row in cursor.fetchall()}
        
        # Total trials
        cursor.execute('SELECT COUNT(*) as count FROM server_trials')
        stats['total_trials'] = cursor.fetchone()['count']
        
        # Active machines
        cursor.execute('SELECT COUNT(*) as count FROM server_machines WHERE is_active = 1')
        stats['active_machines'] = cursor.fetchone()['count']
        
        # Recent validations (last 24h)
        cursor.execute('''
            SELECT COUNT(*) as count FROM license_validation_log 
            WHERE created_at > datetime('now', '-24 hours')
        ''')
        stats['validations_24h'] = cursor.fetchone()['count']
        
        return stats
        
    except Exception as e:
        print(f"[DATABASE] Error getting license stats: {e}")
        return {}


# ==================== SIGNAL FORMAT LEARNING (AI-POWERED) ====================

def init_signal_formats_table():
    """Initialize the signal_formats table for learned parsing patterns."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signal_formats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            example_signal TEXT NOT NULL,
            parsed_fields TEXT NOT NULL,
            regex_pattern TEXT,
            field_mappings TEXT NOT NULL,
            is_enabled INTEGER DEFAULT 1,
            usage_count INTEGER DEFAULT 0,
            success_rate REAL DEFAULT 100.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT DEFAULT 'chatbot'
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signal_format_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_hash TEXT UNIQUE NOT NULL,
            format_id INTEGER,
            parsed_result TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (format_id) REFERENCES signal_formats(id)
        )
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_signal_formats_enabled ON signal_formats(is_enabled)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_signal_format_cache_hash ON signal_format_cache(message_hash)
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS countries (
            code VARCHAR(3) PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            currency VARCHAR(3) NOT NULL,
            timezone VARCHAR(50) NOT NULL,
            flag_emoji VARCHAR(10),
            market_open_time VARCHAR(10),
            market_close_time VARCHAR(10),
            enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        INSERT OR IGNORE INTO countries (code, name, currency, timezone, flag_emoji, market_open_time, market_close_time)
        VALUES 
            ('US', 'United States', 'USD', 'America/New_York', '🇺🇸', '09:30', '16:00'),
            ('CA', 'Canada', 'CAD', 'America/Toronto', '🇨🇦', '09:30', '16:00'),
            ('IN', 'India', 'INR', 'Asia/Kolkata', '🇮🇳', '09:15', '15:30')
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS broker_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country_code VARCHAR(3) NOT NULL,
            broker_name VARCHAR(50) NOT NULL UNIQUE,
            display_name VARCHAR(100) NOT NULL,
            credential_fields TEXT NOT NULL,
            python_library VARCHAR(100),
            supports_options INTEGER DEFAULT 1,
            supports_stocks INTEGER DEFAULT 1,
            supports_paper INTEGER DEFAULT 0,
            token_expiry_info VARCHAR(200),
            enabled INTEGER DEFAULT 1,
            display_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (country_code) REFERENCES countries(code)
        )
    ''')
    
    cursor.execute('''
        INSERT OR IGNORE INTO broker_profiles 
        (country_code, broker_name, display_name, credential_fields, python_library, supports_options, supports_stocks, supports_paper, token_expiry_info, display_order)
        VALUES 
            ('US', 'webull', 'Webull', '["email","password","device_id","trading_pin","mfa_code"]', 'webull', 1, 1, 1, 'Session-based', 1),
            ('US', 'alpaca', 'Alpaca', '["api_key","secret_key"]', 'alpaca-py', 1, 1, 1, 'No expiry', 2),
            ('US', 'ibkr', 'Interactive Brokers', '["username","password","account_id"]', 'ib-insync', 1, 1, 1, 'Session-based', 3),
            ('US', 'tastytrade', 'Tastytrade', '["username","password","client_secret","refresh_token"]', 'tastytrade', 1, 1, 1, '15-minute token', 4),
            ('US', 'robinhood', 'Robinhood', '["username","password","totp_secret"]', 'robin-stocks', 1, 1, 0, 'Session-based', 5),
            ('US', 'SCHWAB', 'Charles Schwab', '["client_id","client_secret","redirect_uri"]', 'httpx', 1, 1, 0, '30-min access / 7-day refresh', 6),
            ('CA', 'questrade', 'Questrade', '["refresh_token"]', 'qtrade', 1, 1, 0, '30-min access / 3-day refresh', 1),
            ('IN', 'upstox', 'Upstox', '["api_key","api_secret","redirect_uri","access_token","refresh_token","token_issued_at"]', 'upstox-python-sdk', 1, 1, 0, '24h access / auto-refresh', 1),
            ('IN', 'zerodha', 'Zerodha (Kite)', '["api_key","api_secret","access_token","request_token"]', 'kiteconnect', 1, 1, 0, 'Daily 6 AM IST', 2),
            ('IN', 'dhanq', 'DhanQ', '["client_id","access_token"]', 'dhanhq', 1, 1, 0, '24 hours (auto-refresh available)', 3)
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS broker_credentials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            broker_name VARCHAR(50) NOT NULL UNIQUE,
            country_code VARCHAR(3) NOT NULL,
            credentials_encrypted TEXT,
            is_connected INTEGER DEFAULT 0,
            last_connected_at TIMESTAMP,
            connection_status VARCHAR(200),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (broker_name) REFERENCES broker_profiles(broker_name),
            FOREIGN KEY (country_code) REFERENCES countries(code)
        )
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_broker_profiles_country ON broker_profiles(country_code)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_broker_credentials_broker ON broker_credentials(broker_name)
    ''')
    
    # Migration: Ensure Schwab exists in broker_profiles for existing databases
    cursor.execute('''
        INSERT OR IGNORE INTO broker_profiles 
        (country_code, broker_name, display_name, credential_fields, python_library, supports_options, supports_stocks, supports_paper, token_expiry_info, display_order, enabled)
        VALUES ('US', 'SCHWAB', 'Charles Schwab', '["client_id","client_secret","redirect_uri"]', 'httpx', 1, 1, 0, '30-min access / 7-day refresh', 6, 1)
    ''')
    
    # Migration: Fix Zerodha credential fields to match API requirements
    cursor.execute('''
        UPDATE broker_profiles 
        SET credential_fields = '["api_key","api_secret","access_token","request_token"]'
        WHERE broker_name = 'zerodha'
    ''')
    
    conn.commit()


def get_learned_signal_formats(enabled_only: bool = True) -> List[Dict]:
    """Get all learned signal formats from database."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        if enabled_only:
            cursor.execute('''
                SELECT * FROM signal_formats 
                WHERE is_enabled = 1 
                ORDER BY usage_count DESC, created_at DESC
            ''')
        else:
            cursor.execute('''
                SELECT * FROM signal_formats 
                ORDER BY is_enabled DESC, usage_count DESC, created_at DESC
            ''')
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"[DATABASE] Error getting signal formats: {e}")
        return []


def save_learned_signal_format(name: str, description: str, example_signal: str,
                                parsed_fields: Dict, regex_pattern: str,
                                field_mappings: Dict, created_by: str = 'chatbot') -> Optional[int]:
    """Save a new learned signal format to database."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO signal_formats 
            (name, description, example_signal, parsed_fields, regex_pattern, field_mappings, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            name, description, example_signal,
            json.dumps(parsed_fields), regex_pattern, json.dumps(field_mappings), created_by
        ))
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        print(f"[DATABASE] Error saving signal format: {e}")
        return None


def update_signal_format(format_id: int, **kwargs) -> bool:
    """Update a signal format's fields."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        allowed_fields = ['name', 'description', 'regex_pattern', 'field_mappings', 
                          'is_enabled', 'usage_count', 'success_rate']
        updates = {}
        for k, v in kwargs.items():
            if k in allowed_fields:
                if k == 'field_mappings' and isinstance(v, dict):
                    v = json.dumps(v)
                updates[k] = v
        
        if not updates:
            return False
        
        updates['updated_at'] = datetime.now().isoformat()
        set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [format_id]
        
        cursor.execute(f'''
            UPDATE signal_formats SET {set_clause} WHERE id = ?
        ''', values)
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"[DATABASE] Error updating signal format: {e}")
        return False


def delete_signal_format(format_id: int) -> bool:
    """Delete a signal format."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('DELETE FROM signal_format_cache WHERE format_id = ?', (format_id,))
        cursor.execute('DELETE FROM signal_formats WHERE id = ?', (format_id,))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"[DATABASE] Error deleting signal format: {e}")
        return False


def increment_format_usage(format_id: int, success: bool = True) -> bool:
    """Increment usage count and update success rate for a format."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT usage_count, success_rate FROM signal_formats WHERE id = ?', (format_id,))
        row = cursor.fetchone()
        if not row:
            return False
        
        usage_count = row['usage_count'] + 1
        old_rate = row['success_rate']
        new_rate = ((old_rate * (usage_count - 1)) + (100.0 if success else 0.0)) / usage_count
        
        cursor.execute('''
            UPDATE signal_formats 
            SET usage_count = ?, success_rate = ?, updated_at = ?
            WHERE id = ?
        ''', (usage_count, new_rate, datetime.now().isoformat(), format_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DATABASE] Error incrementing format usage: {e}")
        return False


def get_cached_signal_parse(message_hash: str) -> Optional[Dict]:
    """Get cached parse result for a message hash."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT parsed_result, format_id FROM signal_format_cache 
            WHERE message_hash = ?
        ''', (message_hash,))
        row = cursor.fetchone()
        if row and row['parsed_result']:
            return {
                'parsed_result': json.loads(row['parsed_result']),
                'format_id': row['format_id']
            }
        return None
    except Exception as e:
        print(f"[DATABASE] Error getting cached parse: {e}")
        return None


def cache_signal_parse(message_hash: str, format_id: Optional[int], parsed_result: Dict) -> bool:
    """Cache a parse result for future use."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO signal_format_cache (message_hash, format_id, parsed_result)
            VALUES (?, ?, ?)
        ''', (message_hash, format_id, json.dumps(parsed_result)))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DATABASE] Error caching parse: {e}")
        return False


def cleanup_old_cache(days: int = 7) -> int:
    """Clean up cache entries older than specified days."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            DELETE FROM signal_format_cache 
            WHERE created_at < datetime('now', ?)
        ''', (f'-{days} days',))
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        print(f"[DATABASE] Error cleaning cache: {e}")
        return 0


# Aliases for chat_assistant compatibility
def save_signal_format(name: str, description: str, example_signal: str,
                       parsed_fields: Dict, field_mappings: Dict, 
                       regex_pattern: Optional[str] = None) -> Optional[int]:
    """Alias for save_learned_signal_format."""
    return save_learned_signal_format(name, description, example_signal, 
                                       parsed_fields, field_mappings, regex_pattern)


def get_signal_formats(enabled_only: bool = False) -> List[Dict]:
    """Alias for get_learned_signal_formats."""
    return get_learned_signal_formats(enabled_only)


def toggle_signal_format(format_name: str, enabled: bool) -> bool:
    """Toggle a signal format's enabled state by name."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE signal_formats 
            SET is_enabled = ?, updated_at = ?
            WHERE name = ?
        ''', (1 if enabled else 0, datetime.now().isoformat(), format_name))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"[DATABASE] Error toggling signal format: {e}")
        return False


def delete_signal_format_by_name(format_name: str) -> bool:
    """Delete a signal format by name."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Get the format_id first
        cursor.execute('SELECT id FROM signal_formats WHERE name = ?', (format_name,))
        row = cursor.fetchone()
        if not row:
            return False
        
        format_id = row['id']
        cursor.execute('DELETE FROM signal_format_cache WHERE format_id = ?', (format_id,))
        cursor.execute('DELETE FROM signal_formats WHERE id = ?', (format_id,))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"[DATABASE] Error deleting signal format by name: {e}")
        return False


# ============ CHANNEL MESSAGES TABLE (for format discovery) ============

def init_channel_messages_table():
    """Initialize channel messages table for format discovery."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channel_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL,
                channel_name TEXT,
                message_content TEXT NOT NULL,
                author_id TEXT,
                author_name TEXT,
                message_id TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_channel_messages_channel ON channel_messages(channel_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_channel_messages_created ON channel_messages(created_at)')
        
        conn.commit()
    except Exception as e:
        print(f"[DATABASE] Error creating channel_messages table: {e}")


def save_channel_message(channel_id: str, message_content: str, 
                         channel_name: str = None, author_id: str = None,
                         author_name: str = None, message_id: str = None) -> bool:
    """Save a message from a Discord channel for format discovery."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO channel_messages 
            (channel_id, channel_name, message_content, author_id, author_name, message_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (str(channel_id), channel_name, message_content, 
              str(author_id) if author_id else None, 
              author_name, str(message_id) if message_id else None,
              datetime.now().isoformat()))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DATABASE] Error saving channel message: {e}")
        return False


def get_recent_channel_messages(channel_id: str, limit: int = 50) -> List[str]:
    """Get recent messages from a channel for format discovery."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT message_content FROM channel_messages 
            WHERE channel_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        ''', (str(channel_id), limit))
        
        return [row['message_content'] for row in cursor.fetchall()]
    except Exception as e:
        print(f"[DATABASE] Error getting channel messages: {e}")
        return []


def get_all_channels_with_messages() -> List[Dict]:
    """Get list of channels that have stored messages."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT channel_id, channel_name, COUNT(*) as message_count,
                   MAX(created_at) as last_message
            FROM channel_messages
            GROUP BY channel_id
            ORDER BY last_message DESC
        ''')
        
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"[DATABASE] Error getting channels: {e}")
        return []


def cleanup_old_channel_messages(days: int = 30) -> int:
    """Clean up channel messages older than specified days."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            DELETE FROM channel_messages 
            WHERE created_at < datetime('now', ?)
        ''', (f'-{days} days',))
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        print(f"[DATABASE] Error cleaning channel messages: {e}")
        return 0


# ==================== DEBUG REPORTS ====================

def generate_debug_reference() -> str:
    """Generate a unique debug report reference number."""
    import random
    import string
    date_part = datetime.now().strftime('%Y%m%d')
    rand_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"DBG-{date_part}-{rand_part}"


def save_debug_report(reference_number: str, user_description: str, error_logs: str, 
                      system_info: str, admin_email: str = None) -> bool:
    """Save a debug report to the database."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO debug_reports (reference_number, user_description, error_logs, 
                                       system_info, admin_email)
            VALUES (?, ?, ?, ?, ?)
        ''', (reference_number, user_description, error_logs, system_info, admin_email))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DATABASE] Error saving debug report: {e}")
        return False


def update_debug_report_sent(reference_number: str) -> bool:
    """Mark a debug report as sent via email."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE debug_reports 
            SET email_sent = 1, email_sent_at = CURRENT_TIMESTAMP, status = 'sent'
            WHERE reference_number = ?
        ''', (reference_number,))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"[DATABASE] Error updating debug report: {e}")
        return False


def get_debug_report(reference_number: str) -> Optional[Dict]:
    """Get a debug report by reference number."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT * FROM debug_reports WHERE reference_number = ?
        ''', (reference_number,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DATABASE] Error getting debug report: {e}")
        return None


def get_recent_debug_reports(limit: int = 10) -> List[Dict]:
    """Get recent debug reports."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT reference_number, user_description, status, email_sent, created_at
            FROM debug_reports
            ORDER BY created_at DESC
            LIMIT ?
        ''', (limit,))
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"[DATABASE] Error getting debug reports: {e}")
        return []


# ==================== TRADE MONITOR ====================

def get_trade_monitor_settings() -> Dict[str, Any]:
    """Get trade monitor settings."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT * FROM trade_monitor_settings WHERE id = 1')
        row = cursor.fetchone()
        if row:
            return dict(row)
        return {
            'enabled': False,
            'poll_interval_seconds': 10,
            'target_webhook_channel_id': None,
            'include_stocks': True,
            'include_options': True,
            'post_bto_signals': True,
            'post_stc_signals': True
        }
    except Exception as e:
        print(f"[DATABASE] Error getting trade monitor settings: {e}")
        return {'enabled': False}


def save_trade_monitor_settings(enabled: bool, poll_interval: int = 10, 
                                 target_channel_id: str = None,
                                 include_stocks: bool = True, include_options: bool = True,
                                 post_bto: bool = True, post_stc: bool = True) -> bool:
    """Save trade monitor settings."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE trade_monitor_settings 
            SET enabled = ?, poll_interval_seconds = ?, target_webhook_channel_id = ?,
                include_stocks = ?, include_options = ?, 
                post_bto_signals = ?, post_stc_signals = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''', (1 if enabled else 0, poll_interval, target_channel_id,
              1 if include_stocks else 0, 1 if include_options else 0,
              1 if post_bto else 0, 1 if post_stc else 0))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DATABASE] Error saving trade monitor settings: {e}")
        return False


def is_order_synced(broker: str, order_id: str) -> bool:
    """Check if an order has already been synced."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT 1 FROM synced_orders WHERE broker = ? AND order_id = ?
        ''', (broker, order_id))
        return cursor.fetchone() is not None
    except Exception as e:
        print(f"[DATABASE] Error checking synced order: {e}")
        return False


def add_synced_order(broker: str, order_id: str, symbol: str, action: str,
                     quantity: int = None, filled_price: float = None,
                     asset_type: str = 'stock', strike: float = None,
                     expiry: str = None, direction: str = None,
                     discord_channel_id: str = None) -> bool:
    """Add a synced order to prevent duplicate posts."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO synced_orders 
            (broker, order_id, symbol, action, quantity, filled_price, 
             asset_type, strike, expiry, direction, posted_to_discord, discord_channel_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        ''', (broker, order_id, symbol, action, quantity, filled_price,
              asset_type, strike, expiry, direction, discord_channel_id))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"[DATABASE] Error adding synced order: {e}")
        return False


def get_recent_synced_orders(limit: int = 50) -> List[Dict]:
    """Get recently synced orders."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT * FROM synced_orders 
            ORDER BY synced_at DESC 
            LIMIT ?
        ''', (limit,))
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"[DATABASE] Error getting synced orders: {e}")
        return []


# ==================== COUNTRY & BROKER MANAGEMENT ====================

def get_all_countries(enabled_only: bool = True) -> List[Dict]:
    """Get all countries."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        if enabled_only:
            cursor.execute('SELECT * FROM countries WHERE enabled = 1 ORDER BY code')
        else:
            cursor.execute('SELECT * FROM countries ORDER BY code')
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"[DATABASE] Error getting countries: {e}")
        return []


def get_country(code: str) -> Optional[Dict]:
    """Get a specific country by code."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT * FROM countries WHERE code = ?', (code,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DATABASE] Error getting country {code}: {e}")
        return None


def get_brokers_by_country(country_code: str, enabled_only: bool = True) -> List[Dict]:
    """Get all brokers for a specific country."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        if enabled_only:
            cursor.execute('''
                SELECT * FROM broker_profiles 
                WHERE country_code = ? AND enabled = 1 
                ORDER BY display_order
            ''', (country_code,))
        else:
            cursor.execute('''
                SELECT * FROM broker_profiles 
                WHERE country_code = ? 
                ORDER BY display_order
            ''', (country_code,))
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"[DATABASE] Error getting brokers for {country_code}: {e}")
        return []


def get_all_brokers_grouped() -> Dict[str, List[Dict]]:
    """Get all brokers grouped by country."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT bp.*, c.name as country_name, c.flag_emoji, c.currency
            FROM broker_profiles bp
            JOIN countries c ON bp.country_code = c.code
            WHERE bp.enabled = 1 AND c.enabled = 1
            ORDER BY c.code, bp.display_order
        ''')
        
        result = {}
        for row in cursor.fetchall():
            data = dict(row)
            country = data['country_code']
            if country not in result:
                result[country] = {
                    'name': data['country_name'],
                    'flag': data['flag_emoji'],
                    'currency': data['currency'],
                    'brokers': []
                }
            result[country]['brokers'].append(data)
        return result
    except Exception as e:
        print(f"[DATABASE] Error getting grouped brokers: {e}")
        return {}


def get_broker_profile(broker_name: str) -> Optional[Dict]:
    """Get a specific broker profile."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT bp.*, c.name as country_name, c.flag_emoji, c.currency, c.timezone
            FROM broker_profiles bp
            JOIN countries c ON bp.country_code = c.code
            WHERE bp.broker_name = ?
        ''', (broker_name,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DATABASE] Error getting broker profile {broker_name}: {e}")
        return None


def save_broker_credentials(broker_name: str, country_code: str, credentials: Dict) -> bool:
    """Save encrypted broker credentials."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        credentials_json = json.dumps(credentials)
        
        cursor.execute('''
            INSERT INTO broker_credentials (broker_name, country_code, credentials_encrypted, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(broker_name) DO UPDATE SET
                credentials_encrypted = excluded.credentials_encrypted,
                updated_at = CURRENT_TIMESTAMP
        ''', (broker_name, country_code, credentials_json))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DATABASE] Error saving broker credentials for {broker_name}: {e}")
        return False


def get_broker_credentials(broker_name: str) -> Optional[Dict]:
    """Get broker credentials (decrypted)."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT * FROM broker_credentials WHERE broker_name = ?
        ''', (broker_name,))
        row = cursor.fetchone()
        if row:
            data = dict(row)
            if data.get('credentials_encrypted'):
                data['credentials'] = json.loads(data['credentials_encrypted'])
            else:
                data['credentials'] = {}
            return data
        return None
    except Exception as e:
        print(f"[DATABASE] Error getting broker credentials for {broker_name}: {e}")
        return None


def update_broker_connection_status(broker_name: str, is_connected: bool, status_message: str = None) -> bool:
    """Update broker connection status."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        if is_connected:
            cursor.execute('''
                UPDATE broker_credentials 
                SET is_connected = 1, last_connected_at = CURRENT_TIMESTAMP, 
                    connection_status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE broker_name = ?
            ''', (status_message or 'Connected', broker_name))
        else:
            cursor.execute('''
                UPDATE broker_credentials 
                SET is_connected = 0, connection_status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE broker_name = ?
            ''', (status_message or 'Disconnected', broker_name))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DATABASE] Error updating broker connection status: {e}")
        return False


def get_all_broker_statuses() -> Dict[str, Dict]:
    """Get connection status for all brokers."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT broker_name, country_code, is_connected, last_connected_at, connection_status
            FROM broker_credentials
        ''')
        return {row['broker_name']: dict(row) for row in cursor.fetchall()}
    except Exception as e:
        print(f"[DATABASE] Error getting broker statuses: {e}")
        return {}


# ==================== BROKER STATES (Multi-Broker Dashboard) ====================

def init_broker_states_table():
    """Initialize broker_states table for caching broker balances."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS broker_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                broker_name TEXT NOT NULL UNIQUE,
                country_code TEXT NOT NULL,
                region TEXT NOT NULL,
                is_connected INTEGER DEFAULT 0,
                balance REAL DEFAULT 0,
                buying_power REAL DEFAULT 0,
                currency TEXT DEFAULT 'USD',
                account_id TEXT,
                account_number TEXT,
                is_paper INTEGER DEFAULT 0,
                last_sync_at TEXT,
                sync_error TEXT,
                extra_data TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        return True
    except Exception as e:
        print(f"[DATABASE] Error creating broker_states table: {e}")
        return False


def update_broker_state(broker_name: str, country_code: str, state: Dict) -> bool:
    """Update or insert broker state (balance snapshot)."""
    conn = get_connection()
    cursor = conn.cursor()
    
    region_map = {'US': 'USA', 'CA': 'Canada', 'IN': 'India'}
    region = region_map.get(country_code, 'USA')
    
    try:
        extra_data = json.dumps(state.get('extra', {})) if state.get('extra') else None
        
        cursor.execute('''
            INSERT INTO broker_states (broker_name, country_code, region, is_connected, balance, 
                buying_power, currency, account_id, account_number, is_paper, last_sync_at, sync_error, extra_data, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(broker_name) DO UPDATE SET
                is_connected = excluded.is_connected,
                balance = excluded.balance,
                buying_power = excluded.buying_power,
                currency = excluded.currency,
                account_id = excluded.account_id,
                account_number = excluded.account_number,
                is_paper = excluded.is_paper,
                last_sync_at = CURRENT_TIMESTAMP,
                sync_error = excluded.sync_error,
                extra_data = excluded.extra_data,
                updated_at = CURRENT_TIMESTAMP
        ''', (
            broker_name, country_code, region,
            1 if state.get('is_connected') else 0,
            state.get('balance', 0),
            state.get('buying_power', 0),
            state.get('currency', 'USD'),
            state.get('account_id'),
            state.get('account_number'),
            1 if state.get('is_paper') else 0,
            state.get('sync_error'),
            extra_data
        ))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DATABASE] Error updating broker state for {broker_name}: {e}")
        return False


def get_broker_state(broker_name: str) -> Optional[Dict]:
    """Get current state for a specific broker."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT * FROM broker_states WHERE broker_name = ?', (broker_name,))
        row = cursor.fetchone()
        if row:
            data = dict(row)
            if data.get('extra_data'):
                data['extra'] = json.loads(data['extra_data'])
            return data
        return None
    except Exception as e:
        print(f"[DATABASE] Error getting broker state: {e}")
        return None


def get_all_broker_states() -> List[Dict]:
    """Get all broker states grouped by region."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT * FROM broker_states ORDER BY region, broker_name
        ''')
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"[DATABASE] Error getting all broker states: {e}")
        return []


def get_broker_states_by_region(region: str) -> List[Dict]:
    """Get broker states for a specific region (USA, Canada, India)."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT * FROM broker_states WHERE region = ? ORDER BY broker_name
        ''', (region,))
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"[DATABASE] Error getting broker states for region {region}: {e}")
        return []


def get_connected_brokers() -> List[Dict]:
    """Get all connected brokers."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT * FROM broker_states WHERE is_connected = 1 ORDER BY region, broker_name
        ''')
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"[DATABASE] Error getting connected brokers: {e}")
        return []


# ==================== SIGNAL DEDUPLICATION FUNCTIONS ====================

def compute_signal_fingerprint(channel_id: str, ticker: str, entry_price: float, direction: str = 'BTO') -> str:
    """
    Compute a fingerprint for signal deduplication.
    
    Fingerprint = channel_id + ticker + normalized_entry_price + direction
    Entry price is rounded to 2 decimals for fuzzy matching.
    """
    import hashlib
    normalized_price = round(entry_price, 2)
    fingerprint_data = f"{channel_id}:{ticker.upper()}:{normalized_price}:{direction.upper()}"
    return hashlib.md5(fingerprint_data.encode()).hexdigest()[:16]


def check_signal_instance(channel_id: str, ticker: str, entry_price: float, direction: str = 'BTO') -> Optional[Dict]:
    """
    Check if there's an open signal instance for this signal.
    
    Returns the existing instance if found and still OPEN, None otherwise.
    Also expires instances older than their TTL.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    fingerprint = compute_signal_fingerprint(channel_id, ticker, entry_price, direction)
    
    try:
        cursor.execute('''
            UPDATE signal_instances 
            SET status = 'EXPIRED', closed_at = CURRENT_TIMESTAMP, close_reason = 'TTL expired'
            WHERE status = 'OPEN' 
            AND datetime(first_seen, '+' || ttl_hours || ' hours') < datetime('now')
        ''')
        conn.commit()
        
        cursor.execute('''
            SELECT * FROM signal_instances 
            WHERE fingerprint = ? AND channel_id = ? AND status = 'OPEN'
        ''', (fingerprint, str(channel_id)))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DEDUPE] Error checking signal instance: {e}")
        return None


def create_signal_instance(
    channel_id: str,
    ticker: str,
    entry_price: float,
    direction: str = 'BTO',
    quantity: int = 1,
    author_id: str = None,
    author_name: str = None,
    message_id: str = None,
    stop_loss: float = None,
    profit_targets: List[float] = None,
    ttl_hours: int = 24
) -> Optional[int]:
    """
    Create a new signal instance for tracking.
    
    Returns the instance ID if created, None if failed (usually duplicate).
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    fingerprint = compute_signal_fingerprint(channel_id, ticker, entry_price, direction)
    targets_json = json.dumps(profit_targets) if profit_targets else None
    
    try:
        cursor.execute('''
            DELETE FROM signal_instances 
            WHERE channel_id = ? AND fingerprint = ? AND status IN ('CLOSED', 'EXPIRED')
        ''', (str(channel_id), fingerprint))
        
        cursor.execute('''
            INSERT INTO signal_instances 
            (channel_id, ticker, entry_price, direction, quantity, remaining_qty, author_id, author_name, fingerprint, 
             first_message_id, last_message_id, discord_message_id, original_sl, current_sl, stop_loss, profit_targets, ttl_hours)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            str(channel_id), ticker.upper(), entry_price, direction.upper(),
            quantity, quantity,
            author_id, author_name, fingerprint, message_id, message_id, message_id,
            stop_loss, stop_loss, stop_loss, targets_json, ttl_hours
        ))
        conn.commit()
        print(f"[DEDUPE] ✓ Created signal instance: {ticker} @ {entry_price} x{quantity} (fingerprint: {fingerprint})")
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        print(f"[DEDUPE] Signal instance already OPEN for {ticker} @ {entry_price}")
        return None
    except Exception as e:
        print(f"[DEDUPE] Error creating signal instance: {e}")
        return None


def update_signal_instance(
    instance_id: int,
    message_id: str = None,
    stop_loss: float = None,
    profit_targets: List[float] = None
) -> bool:
    """
    Update an existing signal instance (e.g., when SL or PTs change).
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        updates = ["update_count = update_count + 1", "last_updated = CURRENT_TIMESTAMP"]
        params = []
        
        if message_id:
            updates.append("last_message_id = ?")
            params.append(message_id)
        if stop_loss is not None:
            updates.append("stop_loss = ?")
            params.append(stop_loss)
        if profit_targets:
            updates.append("profit_targets = ?")
            params.append(json.dumps(profit_targets))
        
        params.append(instance_id)
        
        cursor.execute(f'''
            UPDATE signal_instances SET {', '.join(updates)} WHERE id = ?
        ''', params)
        conn.commit()
        print(f"[DEDUPE] ✓ Updated signal instance ID {instance_id}")
        return True
    except Exception as e:
        print(f"[DEDUPE] Error updating signal instance: {e}")
        return False


def close_signal_instance(
    channel_id: str = None,
    ticker: str = None,
    instance_id: int = None,
    close_reason: str = 'exit_signal'
) -> bool:
    """
    Close a signal instance (mark as CLOSED so future signals can create new entry).
    
    Can close by instance_id directly, or by channel_id + ticker.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        if instance_id:
            cursor.execute('''
                UPDATE signal_instances 
                SET status = 'CLOSED', closed_at = CURRENT_TIMESTAMP, close_reason = ?
                WHERE id = ?
            ''', (close_reason, instance_id))
        elif channel_id and ticker:
            cursor.execute('''
                UPDATE signal_instances 
                SET status = 'CLOSED', closed_at = CURRENT_TIMESTAMP, close_reason = ?
                WHERE channel_id = ? AND ticker = ? AND status = 'OPEN'
            ''', (close_reason, str(channel_id), ticker.upper()))
        else:
            return False
        
        conn.commit()
        rows_affected = cursor.rowcount
        if rows_affected > 0:
            print(f"[DEDUPE] ✓ Closed {rows_affected} signal instance(s): {ticker or instance_id} - {close_reason}")
        return rows_affected > 0
    except Exception as e:
        print(f"[DEDUPE] Error closing signal instance: {e}")
        return False


def get_open_signal_instances(channel_id: str = None) -> List[Dict]:
    """Get all open signal instances, optionally filtered by channel."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        if channel_id:
            cursor.execute('''
                SELECT * FROM signal_instances 
                WHERE channel_id = ? AND status = 'OPEN'
                ORDER BY first_seen DESC
            ''', (str(channel_id),))
        else:
            cursor.execute('''
                SELECT * FROM signal_instances 
                WHERE status = 'OPEN'
                ORDER BY first_seen DESC
            ''')
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"[DEDUPE] Error getting open instances: {e}")
        return []


# ==================== OMS/RMS HELPER FUNCTIONS ====================

def get_signal_instance_by_message_id(message_id: str) -> Optional[Dict]:
    """Look up signal instance by Discord message ID for edit tracking."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT * FROM signal_instances 
            WHERE discord_message_id = ? AND status = 'OPEN'
            ORDER BY first_seen DESC LIMIT 1
        ''', (str(message_id),))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"[OMS] Error getting instance by message_id: {e}")
        return None


def update_signal_instance_oms(instance_id: int, updates: Dict) -> bool:
    """
    Update signal instance with OMS/RMS fields.
    
    Supports: discord_message_id, discord_channel_id, original_sl, current_sl,
    sl_order_id, pt_order_ids, entry_order_id, hit_level_count, exit_processed,
    exit_source, exit_strategy_mode, sl_version, broker, remaining_qty
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    allowed_fields = [
        'discord_message_id', 'discord_channel_id', 'original_sl', 'current_sl',
        'sl_order_id', 'pt_order_ids', 'entry_order_id', 'hit_level_count',
        'exit_processed', 'exit_source', 'exit_strategy_mode', 'sl_version',
        'broker', 'remaining_qty', 'stop_loss', 'last_message_id'
    ]
    
    try:
        set_clauses = []
        params = []
        
        for field, value in updates.items():
            if field in allowed_fields:
                set_clauses.append(f"{field} = ?")
                params.append(value)
        
        if not set_clauses:
            return False
        
        set_clauses.append("last_updated = CURRENT_TIMESTAMP")
        params.append(instance_id)
        
        cursor.execute(f'''
            UPDATE signal_instances 
            SET {', '.join(set_clauses)}
            WHERE id = ?
        ''', params)
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"[OMS] Error updating signal instance: {e}")
        return False


def update_signal_instance_sl_atomic(
    instance_id: int,
    new_sl: float,
    expected_version: int,
    source: str = 'signal'
) -> bool:
    """
    Atomically update SL only if version matches (optimistic locking).
    
    Returns True if update succeeded, False if version mismatch.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE signal_instances 
            SET current_sl = ?, 
                sl_version = sl_version + 1,
                exit_source = ?,
                last_updated = CURRENT_TIMESTAMP
            WHERE id = ? AND sl_version = ?
        ''', (new_sl, source, instance_id, expected_version))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"[OMS] Error in atomic SL update: {e}")
        return False


def get_global_risk_settings() -> Dict:
    """Get global risk management settings."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT * FROM global_risk_settings WHERE id = 1')
        row = cursor.fetchone()
        if row:
            return dict(row)
        return {
            'enable_signal_update_automation': False,
            'exit_strategy_mode': 'signal',
            'enable_circuit_breaker': False,
            'enable_trailing_execution': False,
            'global_daily_loss_limit': 0,
            'global_max_positions': 10,
            'order_timeout_minutes': 5
        }
    except Exception as e:
        print(f"[OMS] Error getting global risk settings: {e}")
        return {}


def update_global_risk_settings(updates: Dict) -> bool:
    """Update global risk management settings."""
    conn = get_connection()
    cursor = conn.cursor()
    
    allowed_fields = [
        'enable_signal_update_automation', 'exit_strategy_mode',
        'enable_circuit_breaker', 'enable_trailing_execution',
        'global_daily_loss_limit', 'global_max_positions',
        'order_timeout_minutes', 'acknowledged_v2_features'
    ]
    
    try:
        set_clauses = []
        params = []
        
        for field, value in updates.items():
            if field in allowed_fields:
                set_clauses.append(f"{field} = ?")
                params.append(value)
        
        if not set_clauses:
            return False
        
        set_clauses.append("updated_at = CURRENT_TIMESTAMP")
        
        cursor.execute(f'''
            UPDATE global_risk_settings 
            SET {', '.join(set_clauses)}
            WHERE id = 1
        ''', params)
        conn.commit()
        return True
    except Exception as e:
        print(f"[OMS] Error updating global risk settings: {e}")
        return False


def log_risk_event(
    event_type: str,
    signal_instance_id: int = None,
    channel_id: str = None,
    source: str = None,
    details: Dict = None,
    before_state: Dict = None,
    after_state: Dict = None
) -> bool:
    """Log an immutable risk event for audit trail."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO risk_events (
                event_type, signal_instance_id, channel_id, source,
                details, before_state, after_state
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            event_type,
            signal_instance_id,
            channel_id,
            source,
            json.dumps(details) if details else None,
            json.dumps(before_state) if before_state else None,
            json.dumps(after_state) if after_state else None
        ))
        conn.commit()
        print(f"[AUDIT] {event_type}: instance={signal_instance_id}, source={source}")
        return True
    except Exception as e:
        print(f"[AUDIT] Error logging risk event: {e}")
        return False


def is_circuit_breaker_tripped() -> Dict:
    """
    Check if circuit breaker is tripped (trading should be halted).
    
    Returns dict with:
    - tripped: bool - whether trading is halted
    - reason: str - why it was tripped (if applicable)
    - daily_loss: float - current day's realized loss
    - limit: float - configured daily loss limit
    """
    settings = get_global_risk_settings()
    
    if not settings.get('enable_circuit_breaker'):
        return {'tripped': False, 'reason': None, 'daily_loss': 0, 'limit': 0}
    
    daily_loss_limit = settings.get('global_daily_loss_limit', 0)
    max_positions = settings.get('global_max_positions', 10)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT COALESCE(SUM(CASE WHEN pnl < 0 THEN pnl ELSE 0 END), 0) as daily_loss
            FROM signal_instances 
            WHERE DATE(closed_at) = DATE('now') AND status = 'closed'
        ''')
        row = cursor.fetchone()
        daily_loss = abs(row[0]) if row else 0
        
        cursor.execute('''
            SELECT COUNT(*) FROM signal_instances WHERE status = 'open'
        ''')
        open_positions = cursor.fetchone()[0] or 0
        
        if daily_loss_limit > 0 and daily_loss >= daily_loss_limit:
            log_risk_event('CIRCUIT_BREAKER_TRIPPED', source='daily_loss_limit',
                          details={'daily_loss': daily_loss, 'limit': daily_loss_limit})
            return {
                'tripped': True,
                'reason': f'Daily loss limit exceeded: ${daily_loss:.2f} >= ${daily_loss_limit:.2f}',
                'daily_loss': daily_loss,
                'limit': daily_loss_limit
            }
        
        if max_positions > 0 and open_positions >= max_positions:
            return {
                'tripped': True,
                'reason': f'Max positions reached: {open_positions} >= {max_positions}',
                'daily_loss': daily_loss,
                'limit': daily_loss_limit,
                'open_positions': open_positions,
                'max_positions': max_positions
            }
        
        return {'tripped': False, 'reason': None, 'daily_loss': daily_loss, 'limit': daily_loss_limit}
    except Exception as e:
        print(f"[CIRCUIT BREAKER] Error checking status: {e}")
        return {'tripped': False, 'reason': None, 'error': str(e)}


def get_effective_exit_strategy_mode(channel_id: str) -> str:
    """Get effective exit strategy mode (channel override or global default)."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT use_global_risk_settings, exit_strategy_mode, exit_strategy_mode_override
            FROM channels WHERE discord_channel_id = ?
        ''', (str(channel_id),))
        row = cursor.fetchone()
        
        if row:
            use_global = row[0] if row[0] is not None else 1
            channel_mode = row[1]
            override = row[2]
            
            if override and override != 'inherit':
                return override
            
            if not use_global and channel_mode:
                return channel_mode
        
        global_settings = get_global_risk_settings()
        return global_settings.get('exit_strategy_mode', 'signal')
    except Exception as e:
        print(f"[OMS] Error getting exit strategy mode: {e}")
        return 'signal'


def is_signal_update_automation_enabled(channel_id: str) -> bool:
    """Check if signal update automation is enabled for this channel."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT use_global_risk_settings, signal_update_automation, signal_update_automation_override
            FROM channels WHERE discord_channel_id = ?
        ''', (str(channel_id),))
        row = cursor.fetchone()
        
        if row:
            use_global = row[0] if row[0] is not None else 1
            channel_automation = row[1]
            override = row[2]
            
            if override == 'on':
                return True
            if override == 'off':
                return False
            
            if not use_global and channel_automation is not None:
                return bool(channel_automation)
        
        global_settings = get_global_risk_settings()
        return bool(global_settings.get('enable_signal_update_automation', False))
    except Exception as e:
        print(f"[OMS] Error checking signal update automation: {e}")
        return False


def get_open_position_for_symbol(channel_id: str, symbol: str) -> Optional[Dict]:
    """
    Get the most recent open position for a symbol in a channel.
    Used for PNL tracking - finds matching BTO for STC signals.
    Also checks signal_instances table for tracked positions.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT id, ticker as symbol, entry_price, 
                   COALESCE(remaining_qty, quantity, 1) as qty,
                   COALESCE(quantity, 1) as original_qty,
                   direction as call_put
            FROM signal_instances 
            WHERE ticker = ? 
            AND channel_id = ?
            AND status = 'OPEN'
            ORDER BY first_seen DESC 
            LIMIT 1
        ''', (symbol.upper(), str(channel_id)))
        
        row = cursor.fetchone()
        if row:
            result = dict(row)
            result['entry_price'] = result.get('entry_price', 0)
            return result
        
        cursor.execute('''
            SELECT id, symbol, strike, call_put, expiry, quantity as qty, quantity as original_qty,
                   COALESCE(executed_price, intended_price) as entry_price
            FROM trades 
            WHERE symbol = ? 
            AND channel_id = ?
            AND direction = 'BTO' 
            AND status IN ('OPEN', 'PENDING', 'open', 'pending')
            ORDER BY id DESC 
            LIMIT 1
        ''', (symbol.upper(), str(channel_id)))
        
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    except Exception as e:
        print(f"[DATABASE] Error getting open position for {channel_id}/{symbol}: {e}")
        return None


def partial_exit_signal_instance(
    channel_id: str,
    ticker: str,
    exit_qty: int,
    close_reason: str = 'partial_exit'
) -> Optional[Dict]:
    """
    Handle partial exit from a signal instance.
    
    Returns dict with remaining_qty and whether position is fully closed.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT id, remaining_qty, entry_price, quantity as original_qty
            FROM signal_instances 
            WHERE ticker = ? AND channel_id = ? AND status = 'OPEN'
            ORDER BY first_seen DESC 
            LIMIT 1
        ''', (ticker.upper(), str(channel_id)))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        instance = dict(row)
        remaining = instance.get('remaining_qty', 1) or 1
        new_remaining = max(0, remaining - exit_qty)
        
        if new_remaining <= 0:
            cursor.execute('''
                UPDATE signal_instances 
                SET status = 'CLOSED', remaining_qty = 0, 
                    closed_at = CURRENT_TIMESTAMP, close_reason = ?
                WHERE id = ?
            ''', (close_reason, instance['id']))
            fully_closed = True
        else:
            cursor.execute('''
                UPDATE signal_instances 
                SET remaining_qty = ?, last_updated = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (new_remaining, instance['id']))
            fully_closed = False
        
        conn.commit()
        
        return {
            'instance_id': instance['id'],
            'entry_price': instance['entry_price'],
            'original_qty': instance.get('original_qty', 1),
            'exited_qty': min(exit_qty, remaining),
            'remaining_qty': new_remaining,
            'fully_closed': fully_closed
        }
    except Exception as e:
        print(f"[DEDUPE] Error with partial exit: {e}")
        return None


# ============ CONDITIONAL ORDERS SERVICE ============

def init_conditional_orders_table():
    """Create conditional_orders table for price-triggered order monitoring"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conditional_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL,
            signal_id TEXT,
            symbol TEXT NOT NULL,
            asset_type TEXT DEFAULT 'stock',
            
            -- Trigger conditions
            trigger_type TEXT NOT NULL,
            trigger_price REAL NOT NULL,
            adjusted_trigger_price REAL,
            
            -- Risk management (from signal or channel)
            stop_loss_type TEXT,
            stop_loss_value REAL,
            take_profit_targets TEXT,
            trailing_stop_enabled INTEGER DEFAULT 0,
            leave_runner INTEGER DEFAULT 0,
            
            -- Position sizing
            size_mode TEXT,
            qty_value REAL,
            calculated_qty INTEGER,
            
            -- Source tracking
            params_source TEXT DEFAULT 'channel',
            
            -- Broker & data source
            broker_primary TEXT NOT NULL,
            data_source_active TEXT,
            fallback_reason TEXT,
            
            -- Status tracking
            status TEXT DEFAULT 'PENDING',
            
            -- Timestamps
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            triggered_at TIMESTAMP,
            executed_at TIMESTAMP,
            
            -- Execution reference
            executed_trade_id INTEGER,
            error_code TEXT,
            error_message TEXT,
            
            -- Original signal content
            original_message TEXT,
            
            -- Metadata
            metadata TEXT,
            
            FOREIGN KEY (channel_id) REFERENCES channels(discord_channel_id)
        )
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_conditional_status ON conditional_orders(status)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_conditional_symbol ON conditional_orders(symbol)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_conditional_channel ON conditional_orders(channel_id)
    ''')
    
    india_columns = [
        ('strike', 'REAL'),
        ('opt_type', 'TEXT'),
        ('market', 'TEXT DEFAULT "US"'),
        ('expiry', 'TEXT'),
        ('lot_size', 'INTEGER'),
        ('lots', 'INTEGER DEFAULT 1'),
        ('current_price', 'REAL'),
        ('price_updated_at', 'TIMESTAMP'),
    ]
    for col_name, col_type in india_columns:
        try:
            cursor.execute(f'ALTER TABLE conditional_orders ADD COLUMN {col_name} {col_type}')
            print(f"[DATABASE] Added column {col_name} to conditional_orders")
        except Exception:
            pass
    
    extended_columns = [
        ('stop_loss_fixed', 'REAL'),
        ('stop_loss_pct', 'REAL'),
        ('target_ranges', 'TEXT'),
        ('partial_exit_plan', 'TEXT'),
        ('linked_message_ids', 'TEXT'),
    ]
    for col_name, col_type in extended_columns:
        try:
            cursor.execute(f'ALTER TABLE conditional_orders ADD COLUMN {col_name} {col_type}')
            print(f"[DATABASE] Added column {col_name} to conditional_orders")
        except Exception:
            pass
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conditional_order_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            previous_status TEXT,
            new_status TEXT,
            event TEXT,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (order_id) REFERENCES conditional_orders(id)
        )
    ''')
    
    conn.commit()
    print("[DATABASE] ✓ Conditional orders tables ready")


def migrate_channels_for_conditional_orders():
    """Add conditional order columns to channels table"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("PRAGMA table_info(channels)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'conditional_order_enabled' not in columns:
            cursor.execute('ALTER TABLE channels ADD COLUMN conditional_order_enabled INTEGER DEFAULT 1')
            print("[DATABASE] ✓ Added conditional_order_enabled column to channels")
        
        if 'trigger_offset_percent' not in columns:
            cursor.execute('ALTER TABLE channels ADD COLUMN trigger_offset_percent REAL DEFAULT 0.0')
            print("[DATABASE] ✓ Added trigger_offset_percent column to channels")
        
        if 'conditional_order_expiry' not in columns:
            cursor.execute("ALTER TABLE channels ADD COLUMN conditional_order_expiry TEXT DEFAULT 'end_of_day'")
            print("[DATABASE] ✓ Added conditional_order_expiry column to channels")
        
        if 'conditional_auto_execute' not in columns:
            cursor.execute('ALTER TABLE channels ADD COLUMN conditional_auto_execute INTEGER DEFAULT 1')
            print("[DATABASE] ✓ Added conditional_auto_execute column to channels")
        
        # Channel-level timeout in minutes (NULL = no timeout configured, must be set explicitly)
        if 'conditional_order_timeout_minutes' not in columns:
            cursor.execute('ALTER TABLE channels ADD COLUMN conditional_order_timeout_minutes INTEGER DEFAULT NULL')
            print("[DATABASE] ✓ Added conditional_order_timeout_minutes column to channels")
        if 'order_timeout_minutes' not in columns:
            cursor.execute('ALTER TABLE channels ADD COLUMN order_timeout_minutes INTEGER DEFAULT NULL')
            print("[DATABASE] ✓ Added order_timeout_minutes column to channels (applies to ALL orders)")
        
        conn.commit()
    except Exception as e:
        print(f"[DATABASE] Error migrating channels for conditional orders: {e}")


def migrate_trades_for_conditional_orders():
    """Add source and conditional_order_id columns to trades table"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("PRAGMA table_info(trades)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'source' not in columns:
            cursor.execute("ALTER TABLE trades ADD COLUMN source TEXT DEFAULT 'signal'")
            print("[DATABASE] ✓ Added source column to trades")
        
        if 'conditional_order_id' not in columns:
            cursor.execute('ALTER TABLE trades ADD COLUMN conditional_order_id INTEGER')
            print("[DATABASE] ✓ Added conditional_order_id column to trades")
        
        conn.commit()
    except Exception as e:
        print(f"[DATABASE] Error migrating trades for conditional orders: {e}")


def init_conditional_order_settings():
    """Initialize global conditional order settings in bot_settings"""
    conn = get_connection()
    cursor = conn.cursor()
    
    default_settings = [
        ('conditional_order_enabled', 'false'),
        ('conditional_order_default_expiry', 'end_of_day'),
        ('conditional_order_finnhub_fallback', 'true'),
        ('conditional_order_rate_limit_threshold', '80'),
    ]
    
    try:
        for key, value in default_settings:
            cursor.execute('''
                INSERT OR IGNORE INTO settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (key, value))
        
        conn.commit()
        print("[DATABASE] ✓ Conditional order settings initialized")
    except Exception as e:
        print(f"[DATABASE] Error initializing conditional order settings: {e}")


def get_conditional_order_settings() -> Dict[str, Any]:
    """Get global conditional order settings"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT key, value FROM settings
            WHERE key LIKE 'conditional_order_%'
        ''')
        
        rows = cursor.fetchall()
        settings = {}
        for row in rows:
            key = row['key'].replace('conditional_order_', '')
            value = row['value']
            if value == 'true':
                settings[key] = True
            elif value == 'false':
                settings[key] = False
            elif value.isdigit():
                settings[key] = int(value)
            else:
                settings[key] = value
        
        return settings
    except Exception as e:
        print(f"[DATABASE] Error getting conditional order settings: {e}")
        return {
            'enabled': False,
            'default_expiry': 'end_of_day',
            'finnhub_fallback': True,
            'rate_limit_threshold': 80
        }


def save_conditional_order_settings(settings: Dict[str, Any]) -> bool:
    """Save global conditional order settings"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        for key, value in settings.items():
            full_key = f'conditional_order_{key}'
            if isinstance(value, bool):
                str_value = 'true' if value else 'false'
            else:
                str_value = str(value)
            
            cursor.execute('''
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP
            ''', (full_key, str_value, str_value))
        
        conn.commit()
        return True
    except Exception as e:
        print(f"[DATABASE] Error saving conditional order settings: {e}")
        return False


def create_conditional_order(
    channel_id: str,
    symbol: str,
    trigger_type: str,
    trigger_price: float,
    broker_primary: str,
    stop_loss_type: str = None,
    stop_loss_value: float = None,
    take_profit_targets: str = None,
    size_mode: str = None,
    qty_value: float = None,
    calculated_qty: int = None,
    params_source: str = 'channel',
    expires_at: str = None,
    original_message: str = None,
    asset_type: str = 'stock',
    adjusted_trigger_price: float = None,
    signal_id: str = None,
    strike: float = None,
    opt_type: str = None,
    market: str = 'US',
    expiry: str = None,
    lot_size: int = None,
    lots: int = None,
    stop_loss_fixed: float = None,
    stop_loss_pct: float = None,
    target_ranges: str = None
) -> Optional[int]:
    """Create a new conditional order"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO conditional_orders (
                channel_id, symbol, trigger_type, trigger_price, adjusted_trigger_price,
                broker_primary, stop_loss_type, stop_loss_value, take_profit_targets,
                size_mode, qty_value, calculated_qty, params_source, expires_at,
                original_message, asset_type, signal_id, strike, opt_type, market, expiry, lot_size, lots,
                stop_loss_fixed, stop_loss_pct, target_ranges, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
        ''', (
            channel_id, symbol.upper(), trigger_type, trigger_price, adjusted_trigger_price,
            broker_primary, stop_loss_type, stop_loss_value, take_profit_targets,
            size_mode, qty_value, calculated_qty, params_source, expires_at,
            original_message, asset_type, signal_id, strike, opt_type, market, expiry, lot_size, lots,
            stop_loss_fixed, stop_loss_pct, target_ranges
        ))
        
        order_id = cursor.lastrowid
        
        market_info = f" [{market}]" if market != 'US' else ""
        option_info = f" {strike}{opt_type}" if strike and opt_type else ""
        sl_info = ""
        if stop_loss_type == 'hybrid' and stop_loss_fixed and stop_loss_pct:
            sl_info = f", SL=${stop_loss_fixed} or {stop_loss_pct}%"
        elif stop_loss_type == 'percent' and stop_loss_value:
            sl_info = f", SL={stop_loss_value}%"
        elif stop_loss_value:
            sl_info = f", SL=${stop_loss_value}"
        cursor.execute('''
            INSERT INTO conditional_order_audit (order_id, previous_status, new_status, event, details)
            VALUES (?, NULL, 'PENDING', 'CREATED', ?)
        ''', (order_id, f'Conditional order created for {symbol}{option_info} {trigger_type} {trigger_price}{market_info}{sl_info}'))
        
        conn.commit()
        print(f"[DATABASE] ✓ Created conditional order #{order_id} for {symbol}{option_info}{market_info}")
        return order_id
    except Exception as e:
        print(f"[DATABASE] Error creating conditional order: {e}")
        conn.rollback()
        return None


def update_conditional_order_status(
    order_id: int,
    new_status: str,
    event: str = None,
    details: str = None,
    **kwargs
) -> bool:
    """Update conditional order status and log to audit"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT status FROM conditional_orders WHERE id = ?', (order_id,))
        row = cursor.fetchone()
        if not row:
            return False
        
        old_status = row['status']
        
        update_fields = ['status = ?']
        update_values = [new_status]
        
        if new_status == 'TRIGGERED':
            update_fields.append('triggered_at = CURRENT_TIMESTAMP')
        elif new_status == 'EXECUTING':
            update_fields.append('executed_at = CURRENT_TIMESTAMP')
        
        for key, value in kwargs.items():
            update_fields.append(f'{key} = ?')
            update_values.append(value)
        
        update_values.append(order_id)
        
        cursor.execute(f'''
            UPDATE conditional_orders
            SET {', '.join(update_fields)}
            WHERE id = ?
        ''', update_values)
        
        cursor.execute('''
            INSERT INTO conditional_order_audit (order_id, previous_status, new_status, event, details)
            VALUES (?, ?, ?, ?, ?)
        ''', (order_id, old_status, new_status, event or f'Status changed to {new_status}', details))
        
        conn.commit()
        return True
    except Exception as e:
        print(f"[DATABASE] Error updating conditional order status: {e}")
        conn.rollback()
        return False


def update_conditional_order_price(order_id: int, current_price: float) -> bool:
    """Update the current price for a conditional order (called during monitoring)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE conditional_orders
            SET current_price = ?, price_updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status IN ('PENDING', 'ACTIVE_MONITORING', 'FALLBACK_MONITORING')
        ''', (current_price, order_id))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        return False


def update_conditional_order_sl_pt(
    order_id: int,
    stop_loss_value: float = None,
    stop_loss_type: str = None,
    stop_loss_fixed: float = None,
    stop_loss_pct: float = None,
    take_profit_target: float = None
) -> bool:
    """
    Update stop loss and/or profit target for a conditional order.
    
    Called when follow-up messages provide delayed SL/PT updates.
    For hybrid SL to work, we preserve BOTH legs - if a follow-up provides one leg,
    we merge it with the existing SIGNAL-PROVIDED leg (not channel defaults).
    
    IMPORTANT: This function only updates values that are explicitly provided.
    Channel-level defaults are applied at EXECUTION time, not during follow-up updates.
    This preserves the Signal→Channel→Default priority hierarchy.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # First, fetch existing SL values to preserve hybrid legs
        cursor.execute('''
            SELECT stop_loss_value, stop_loss_type, stop_loss_fixed, stop_loss_pct, params_source
            FROM conditional_orders WHERE id = ?
        ''', (order_id,))
        existing = cursor.fetchone()
        
        if not existing:
            return False
        
        existing_sl_value = existing['stop_loss_value']
        existing_sl_type = existing['stop_loss_type']
        existing_sl_fixed = existing['stop_loss_fixed']
        existing_sl_pct = existing['stop_loss_pct']
        params_source = existing['params_source'] if 'params_source' in existing.keys() else None
        
        update_fields = []
        update_values = []
        
        # Determine the existing signal-provided fixed leg
        # For legacy rows that only have stop_loss_value (not stop_loss_fixed), treat it as the fixed leg
        # But ONLY if the params_source indicates it came from the signal, not channel defaults
        legacy_fixed_leg = None
        if existing_sl_fixed is not None:
            legacy_fixed_leg = existing_sl_fixed
        elif existing_sl_value is not None and existing_sl_type in ('fixed', 'hybrid', None):
            # Treat stop_loss_value as the fixed leg for legacy/pre-migration data
            legacy_fixed_leg = existing_sl_value
        
        # Calculate final values - only merge with signal-provided values
        final_sl_fixed = stop_loss_fixed if stop_loss_fixed is not None else (
            stop_loss_value if stop_loss_value is not None else legacy_fixed_leg
        )
        final_sl_pct = stop_loss_pct if stop_loss_pct is not None else existing_sl_pct
        
        # Determine if this results in a hybrid SL (both signal-provided legs present)
        is_hybrid = final_sl_fixed is not None and final_sl_pct is not None
        
        # Only update fields that are explicitly provided in this update
        # This prevents overwriting signal/channel values with nulls
        if stop_loss_value is not None or stop_loss_fixed is not None:
            # Updating the fixed price leg
            new_fixed = stop_loss_fixed if stop_loss_fixed is not None else stop_loss_value
            update_fields.append('stop_loss_fixed = ?')
            update_values.append(new_fixed)
            update_fields.append('stop_loss_value = ?')
            update_values.append(new_fixed)
        
        if stop_loss_pct is not None:
            # Updating the percent leg
            update_fields.append('stop_loss_pct = ?')
            update_values.append(stop_loss_pct)
            # If we now have both legs (hybrid), preserve the existing fixed leg
            if is_hybrid and legacy_fixed_leg and stop_loss_value is None and stop_loss_fixed is None:
                update_fields.append('stop_loss_fixed = ?')
                update_values.append(legacy_fixed_leg)
                update_fields.append('stop_loss_value = ?')
                update_values.append(legacy_fixed_leg)
        
        # Set stop_loss_type appropriately based on what we have
        if is_hybrid:
            update_fields.append('stop_loss_type = ?')
            update_values.append('hybrid')
        elif stop_loss_type is not None:
            update_fields.append('stop_loss_type = ?')
            update_values.append(stop_loss_type)
        elif stop_loss_pct is not None and (stop_loss_value is None and stop_loss_fixed is None and legacy_fixed_leg is None):
            # Only percent provided and no fixed leg exists
            update_fields.append('stop_loss_type = ?')
            update_values.append('percent')
        elif (stop_loss_value is not None or stop_loss_fixed is not None) and final_sl_pct is None:
            # Only fixed provided and no percent leg exists
            update_fields.append('stop_loss_type = ?')
            update_values.append('fixed')
        
        if take_profit_target is not None:
            cursor.execute('SELECT take_profit_targets FROM conditional_orders WHERE id = ?', (order_id,))
            row = cursor.fetchone()
            if row:
                existing = row['take_profit_targets'] or ''
                import json
                try:
                    targets = json.loads(existing) if existing else []
                except:
                    targets = [float(t) for t in existing.split(',') if t.strip()] if existing else []
                
                if take_profit_target not in targets:
                    targets.append(take_profit_target)
                    targets.sort()
                
                update_fields.append('take_profit_targets = ?')
                update_values.append(json.dumps(targets))
        
        if not update_fields:
            return False
        
        update_values.append(order_id)
        
        cursor.execute(f'''
            UPDATE conditional_orders
            SET {', '.join(update_fields)}
            WHERE id = ? AND status IN ('PENDING', 'ACTIVE_MONITORING', 'FALLBACK_MONITORING')
        ''', update_values)
        
        if cursor.rowcount > 0:
            update_desc = []
            if stop_loss_value is not None:
                update_desc.append(f"SL=${stop_loss_value}")
            if take_profit_target is not None:
                update_desc.append(f"PT=${take_profit_target}")
            
            cursor.execute('''
                INSERT INTO conditional_order_audit (order_id, previous_status, new_status, event, details)
                VALUES (?, 'PENDING', 'PENDING', 'SL_PT_UPDATE', ?)
            ''', (order_id, f'Updated: {", ".join(update_desc)}'))
            
            conn.commit()
            print(f"[DATABASE] ✓ Updated conditional order #{order_id}: {', '.join(update_desc)}")
            return True
        
        return False
    except Exception as e:
        print(f"[DATABASE] Error updating conditional order SL/PT: {e}")
        conn.rollback()
        return False


def get_active_conditional_orders(market: str = None) -> List[Dict[str, Any]]:
    """Get all active conditional orders that need monitoring, optionally filtered by market"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        if market:
            cursor.execute('''
                SELECT co.*, c.trigger_offset_percent, c.broker_override, c.exit_strategy_mode,
                       c.default_quantity, c.position_size_pct
                FROM conditional_orders co
                LEFT JOIN channels c ON co.channel_id = c.discord_channel_id
                WHERE co.status IN ('PENDING', 'ACTIVE_MONITORING', 'FALLBACK_MONITORING')
                AND (co.expires_at IS NULL OR co.expires_at > CURRENT_TIMESTAMP)
                AND co.market = ?
                ORDER BY co.created_at ASC
            ''', (market,))
        else:
            cursor.execute('''
                SELECT co.*, c.trigger_offset_percent, c.broker_override, c.exit_strategy_mode,
                       c.default_quantity, c.position_size_pct
                FROM conditional_orders co
                LEFT JOIN channels c ON co.channel_id = c.discord_channel_id
                WHERE co.status IN ('PENDING', 'ACTIVE_MONITORING', 'FALLBACK_MONITORING')
                AND (co.expires_at IS NULL OR co.expires_at > CURRENT_TIMESTAMP)
                ORDER BY co.created_at ASC
            ''')
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"[DATABASE] Error getting active conditional orders: {e}")
        return []


def get_conditional_order_by_id(order_id: int) -> Optional[Dict[str, Any]]:
    """Get a single conditional order by ID"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT co.*, c.trigger_offset_percent, c.broker_override, c.exit_strategy_mode,
                   c.default_quantity, c.position_size_pct
            FROM conditional_orders co
            LEFT JOIN channels c ON co.channel_id = c.discord_channel_id
            WHERE co.id = ?
        ''', (order_id,))
        
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    except Exception as e:
        print(f"[DATABASE] Error getting conditional order {order_id}: {e}")
        return None


def get_conditional_orders_by_channel(channel_id: str) -> List[Dict[str, Any]]:
    """Get all conditional orders for a channel"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT * FROM conditional_orders
            WHERE channel_id = ?
            ORDER BY created_at DESC
        ''', (channel_id,))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"[DATABASE] Error getting conditional orders for channel {channel_id}: {e}")
        return []


def cancel_conditional_order(order_id: int, reason: str = 'User cancelled') -> bool:
    """Cancel a conditional order"""
    return update_conditional_order_status(
        order_id, 
        'CANCELED', 
        event='CANCELED',
        details=reason
    )


def purge_conditional_orders(market: str = None, keep_active: bool = True) -> int:
    """Purge completed/cancelled/error conditional orders, optionally filtered by market.
    
    Args:
        market: Optional market filter ('US', 'INDIA', 'CANADA'). If None, purges all markets.
        keep_active: If True, only delete orders that are not actively monitoring
        
    Returns:
        Number of orders deleted
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        non_active_statuses = ('EXECUTED', 'CANCELED', 'CANCELLED', 'ERROR', 'EXPIRED', 'FAILED', 'EXECUTING', 'TRIGGERED')
        placeholders = ','.join(['?' for _ in non_active_statuses])
        
        if market:
            if keep_active:
                cursor.execute(f'''
                    DELETE FROM conditional_orders
                    WHERE market = ? AND status IN ({placeholders})
                ''', (market, *non_active_statuses))
            else:
                cursor.execute('DELETE FROM conditional_orders WHERE market = ?', (market,))
        else:
            if keep_active:
                cursor.execute(f'''
                    DELETE FROM conditional_orders
                    WHERE status IN ({placeholders})
                ''', non_active_statuses)
            else:
                cursor.execute('DELETE FROM conditional_orders')
        
        deleted_count = cursor.rowcount
        conn.commit()
        print(f"[DATABASE] Purged {deleted_count} conditional orders (market={market}, keep_active={keep_active})")
        return deleted_count
    except Exception as e:
        print(f"[DATABASE] Error purging conditional orders: {e}")
        conn.rollback()
        return 0


def update_conditional_order_trigger_offset(order_id: int, offset_percent: float) -> bool:
    """Update the trigger offset for a conditional order and recalculate adjusted price"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT trigger_price, trigger_type FROM conditional_orders WHERE id = ?', (order_id,))
        row = cursor.fetchone()
        if not row:
            return False
        
        trigger_price = row['trigger_price']
        trigger_type = row['trigger_type']
        
        if trigger_type == 'over':
            adjusted_price = trigger_price * (1 + offset_percent / 100)
        else:
            adjusted_price = trigger_price * (1 - offset_percent / 100)
        
        cursor.execute('''
            UPDATE conditional_orders 
            SET adjusted_trigger_price = ?
            WHERE id = ?
        ''', (adjusted_price, order_id))
        
        cursor.execute('''
            INSERT INTO conditional_order_audit (order_id, previous_status, new_status, event, details)
            SELECT id, status, status, 'OFFSET_ADJUSTED', ?
            FROM conditional_orders WHERE id = ?
        ''', (f'Trigger offset adjusted to {offset_percent:+.1f}% -> ${adjusted_price:.2f}', order_id))
        
        conn.commit()
        print(f"[DATABASE] Updated conditional order #{order_id} offset to {offset_percent:+.1f}%")
        return True
    except Exception as e:
        print(f"[DATABASE] Error updating conditional order trigger offset: {e}")
        conn.rollback()
        return False


def expire_old_conditional_orders() -> int:
    """Expire conditional orders that have passed their expiry time"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT id FROM conditional_orders
            WHERE status IN ('PENDING', 'ACTIVE_MONITORING', 'FALLBACK_MONITORING')
            AND expires_at IS NOT NULL
            AND expires_at <= CURRENT_TIMESTAMP
        ''')
        
        rows = cursor.fetchall()
        expired_count = 0
        
        for row in rows:
            update_conditional_order_status(
                row['id'],
                'EXPIRED',
                event='EXPIRED',
                details='Order expired'
            )
            expired_count += 1
        
        return expired_count
    except Exception as e:
        print(f"[DATABASE] Error expiring conditional orders: {e}")
        return 0


def get_channel_conditional_settings(channel_id: str) -> Dict[str, Any]:
    """Get conditional order settings for a specific channel"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT conditional_order_enabled, trigger_offset_percent,
                   conditional_order_expiry, conditional_auto_execute,
                   conditional_order_timeout_minutes, order_timeout_minutes,
                   broker_override, exit_strategy_mode, default_quantity,
                   position_size_pct, stop_loss_pct, profit_target_pct,
                   profit_target_1_pct, profit_target_2_pct, profit_target_3_pct,
                   profit_target_4_pct, trailing_stop_pct, leave_runner_enabled,
                   leave_runner_pct
            FROM channels
            WHERE discord_channel_id = ?
        ''', (channel_id,))
        
        row = cursor.fetchone()
        if row:
            return dict(row)
        return {}
    except Exception as e:
        print(f"[DATABASE] Error getting channel conditional settings: {e}")
        return {}


def get_conditional_orders_by_status(status: str, market: str = None) -> List[Dict[str, Any]]:
    """Get all conditional orders with a specific status, optionally filtered by market"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        if market:
            cursor.execute('''
                SELECT * FROM conditional_orders
                WHERE status = ? AND market = ?
                ORDER BY created_at DESC
            ''', (status, market))
        else:
            cursor.execute('''
                SELECT * FROM conditional_orders
                WHERE status = ?
                ORDER BY created_at DESC
            ''', (status,))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"[DATABASE] Error getting conditional orders by status: {e}")
        return []


def get_all_conditional_orders(market: str = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Get all conditional orders including ERROR/CANCELLED/EXECUTED, optionally filtered by market"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        if market:
            cursor.execute('''
                SELECT * FROM conditional_orders
                WHERE market = ?
                ORDER BY created_at DESC
                LIMIT ?
            ''', (market, limit))
        else:
            cursor.execute('''
                SELECT * FROM conditional_orders
                ORDER BY created_at DESC
                LIMIT ?
            ''', (limit,))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"[DATABASE] Error getting all conditional orders: {e}")
        return []


def get_conditional_order_audit(order_id: int) -> List[Dict[str, Any]]:
    """Get audit trail for a conditional order"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT * FROM conditional_order_audit
            WHERE order_id = ?
            ORDER BY created_at ASC
        ''', (order_id,))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"[DATABASE] Error getting conditional order audit: {e}")
        return []


# ============ UPSTOX PENDING ORDERS ============

def init_upstox_pending_orders_table():
    """Create table for Upstox pending AMO orders during blackout"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS upstox_pending_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pending_order_id TEXT UNIQUE NOT NULL,
            instrument_token TEXT NOT NULL,
            symbol_display TEXT,
            transaction_type TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL,
            order_type TEXT NOT NULL,
            product TEXT NOT NULL,
            slice INTEGER DEFAULT 1,
            
            -- Status: PENDING, SUBMITTED, CANCELLED, FAILED
            status TEXT DEFAULT 'PENDING',
            
            -- Execution info
            submitted_order_ids TEXT,
            error_message TEXT,
            
            -- Timestamps
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            submitted_at TIMESTAMP,
            cancelled_at TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_upstox_pending_status ON upstox_pending_orders(status)
    ''')
    
    conn.commit()
    print("[DATABASE] ✓ Upstox pending orders table ready")


def init_upstox_settings():
    """Initialize Upstox-specific settings"""
    conn = get_connection()
    cursor = conn.cursor()
    
    default_settings = [
        ('upstox_allow_amo_queue', 'true'),
    ]
    
    try:
        for key, value in default_settings:
            cursor.execute('''
                INSERT OR IGNORE INTO settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (key, value))
        
        conn.commit()
    except Exception as e:
        print(f"[DATABASE] Error initializing Upstox settings: {e}")


def get_upstox_amo_queue_enabled() -> bool:
    """Check if Upstox AMO queue is enabled"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT value FROM settings WHERE key = 'upstox_allow_amo_queue'")
        row = cursor.fetchone()
        if row:
            return row['value'].lower() == 'true'
        return True
    except Exception:
        return True


def set_upstox_amo_queue_enabled(enabled: bool):
    """Enable/disable Upstox AMO queue"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES ('upstox_allow_amo_queue', ?, CURRENT_TIMESTAMP)
        ''', ('true' if enabled else 'false',))
        conn.commit()
    except Exception as e:
        print(f"[DATABASE] Error setting Upstox AMO queue: {e}")


def save_upstox_pending_order(order: Dict[str, Any]) -> bool:
    """Save a pending order to the database"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO upstox_pending_orders 
            (pending_order_id, instrument_token, symbol_display, transaction_type, 
             quantity, price, order_type, product, slice, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
        ''', (
            order.get('pending_order_id'),
            order.get('instrument_token'),
            order.get('symbol_display'),
            order.get('transaction_type'),
            order.get('quantity'),
            order.get('price', 0),
            order.get('order_type'),
            order.get('product'),
            1 if order.get('slice', True) else 0
        ))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DATABASE] Error saving pending order: {e}")
        return False


def get_upstox_pending_orders(status: str = 'PENDING') -> List[Dict[str, Any]]:
    """Get all pending Upstox orders with given status"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT * FROM upstox_pending_orders
            WHERE status = ?
            ORDER BY created_at DESC
        ''', (status,))
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"[DATABASE] Error getting pending orders: {e}")
        return []


def get_all_upstox_pending_orders() -> List[Dict[str, Any]]:
    """Get all Upstox pending orders regardless of status"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT * FROM upstox_pending_orders
            ORDER BY created_at DESC
            LIMIT 100
        ''')
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"[DATABASE] Error getting all pending orders: {e}")
        return []


def update_upstox_pending_order_status(pending_order_id: str, status: str, 
                                        order_ids: str = None, error: str = None):
    """Update status of a pending order"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        if status == 'SUBMITTED':
            cursor.execute('''
                UPDATE upstox_pending_orders 
                SET status = ?, submitted_order_ids = ?, submitted_at = CURRENT_TIMESTAMP
                WHERE pending_order_id = ?
            ''', (status, order_ids, pending_order_id))
        elif status == 'CANCELLED':
            cursor.execute('''
                UPDATE upstox_pending_orders 
                SET status = ?, cancelled_at = CURRENT_TIMESTAMP
                WHERE pending_order_id = ?
            ''', (status, pending_order_id))
        elif status == 'FAILED':
            cursor.execute('''
                UPDATE upstox_pending_orders 
                SET status = ?, error_message = ?
                WHERE pending_order_id = ?
            ''', (status, error, pending_order_id))
        else:
            cursor.execute('''
                UPDATE upstox_pending_orders 
                SET status = ?
                WHERE pending_order_id = ?
            ''', (status, pending_order_id))
        
        conn.commit()
    except Exception as e:
        print(f"[DATABASE] Error updating pending order status: {e}")


def cancel_upstox_pending_order(pending_order_id: str) -> bool:
    """Cancel a pending order"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT pending_order_id, status FROM upstox_pending_orders WHERE pending_order_id = ?', (pending_order_id,))
        row = cursor.fetchone()
        print(f"[DATABASE] Looking for order {pending_order_id}: found={row is not None}, current_status={dict(row) if row else 'N/A'}")
        
        cursor.execute('''
            UPDATE upstox_pending_orders 
            SET status = 'CANCELLED', cancelled_at = CURRENT_TIMESTAMP
            WHERE pending_order_id = ? AND status = 'PENDING'
        ''', (pending_order_id,))
        
        conn.commit()
        affected = cursor.rowcount
        print(f"[DATABASE] Cancel result: {affected} row(s) affected")
        return affected > 0
    except Exception as e:
        print(f"[DATABASE] Error cancelling pending order: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================
# SIGNAL TRACKING FUNCTIONS - Full lifecycle tracking
# ============================================================

def save_signal_event(
    channel_id: str,
    message_id: str,
    direction: str,
    asset_type: str,
    symbol: str,
    price: float = None,
    quantity: int = None,
    strike: float = None,
    expiry: str = None,
    call_put: str = None,
    author_name: str = None,
    author_id: str = None,
    guild_id: str = None,
    source_platform: str = 'discord',
    market: str = 'US',
    broker_target: str = None,
    raw_message: str = None,
    execution_status: str = 'DETECTED'
) -> Optional[int]:
    """
    Save a signal event to the database with full tracking info.
    Returns the signal ID or None if failed.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO signals (
                channel_id, message_id, direction, asset_type, symbol, 
                price, quantity, strike, expiry, call_put,
                author_name, author_id, guild_id, source_platform, market,
                broker_target, raw_message, execution_status, detected_at, received_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ''', (
            channel_id, message_id, direction, asset_type, symbol,
            price, quantity, strike, expiry, call_put,
            author_name, author_id, guild_id, source_platform, market,
            broker_target, raw_message, execution_status
        ))
        conn.commit()
        signal_id = cursor.lastrowid
        
        add_signal_transition(signal_id, None, execution_status, 
                             f"Signal detected from {source_platform}")
        
        return signal_id
    except sqlite3.IntegrityError:
        return None
    except Exception as e:
        print(f"[DATABASE] Error saving signal event: {e}")
        return None


def update_signal_status(
    signal_id: int,
    new_status: str,
    broker_target: str = None,
    broker_order_id: str = None,
    broker_response: str = None,
    last_error: str = None,
    pnl_realized: float = None,
    pnl_percent: float = None,
    details: str = None
):
    """Update signal status with optional broker info and P&L"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT execution_status FROM signals WHERE id = ?', (signal_id,))
        row = cursor.fetchone()
        old_status = row[0] if row else None
        
        timestamp_col = None
        if new_status == 'VALIDATED':
            timestamp_col = 'validated_at'
        elif new_status == 'SUBMITTED':
            timestamp_col = 'submitted_at'
        elif new_status in ('EXECUTED', 'REJECTED', 'FAILED'):
            timestamp_col = 'executed_at'
        
        updates = ['execution_status = ?']
        params = [new_status]
        
        if broker_target:
            updates.append('broker_target = ?')
            params.append(broker_target)
        if broker_order_id:
            updates.append('broker_order_id = ?')
            params.append(broker_order_id)
        if broker_response:
            updates.append('broker_response = ?')
            params.append(broker_response)
        if last_error:
            updates.append('last_error = ?')
            params.append(last_error)
        if pnl_realized is not None:
            updates.append('pnl_realized = ?')
            params.append(pnl_realized)
        if pnl_percent is not None:
            updates.append('pnl_percent = ?')
            params.append(pnl_percent)
        if timestamp_col:
            updates.append(f'{timestamp_col} = CURRENT_TIMESTAMP')
        
        params.append(signal_id)
        cursor.execute(f"UPDATE signals SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        
        add_signal_transition(signal_id, old_status, new_status, details or broker_response)
        
    except Exception as e:
        print(f"[DATABASE] Error updating signal status: {e}")


def add_signal_transition(signal_id: int, from_status: str, to_status: str, 
                          details: str = None, actor: str = 'system'):
    """Add an immutable transition record to the audit trail"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO signal_event_transitions (signal_id, from_status, to_status, details, actor)
            VALUES (?, ?, ?, ?, ?)
        ''', (signal_id, from_status, to_status, details, actor))
        conn.commit()
    except Exception as e:
        print(f"[DATABASE] Error adding signal transition: {e}")


def get_signal_history_filtered(
    limit: int = 100,
    offset: int = 0,
    symbol: str = None,
    channel_id: str = None,
    author_id: str = None,
    execution_status: str = None,
    market: str = None,
    broker_target: str = None,
    source_platform: str = None,
    date_from: str = None,
    date_to: str = None
) -> Tuple[List[Dict], int]:
    """
    Get signal history with comprehensive filtering and pagination.
    Returns (signals_list, total_count)
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    where_clauses = []
    params = []
    
    if symbol:
        where_clauses.append('symbol LIKE ?')
        params.append(f'%{symbol}%')
    if channel_id:
        where_clauses.append('channel_id = ?')
        params.append(channel_id)
    if author_id:
        where_clauses.append('author_id = ?')
        params.append(author_id)
    if execution_status:
        where_clauses.append('execution_status = ?')
        params.append(execution_status)
    if market:
        where_clauses.append('market = ?')
        params.append(market)
    if broker_target:
        where_clauses.append('broker_target = ?')
        params.append(broker_target)
    if source_platform:
        where_clauses.append('source_platform = ?')
        params.append(source_platform)
    if date_from:
        where_clauses.append('received_at >= ?')
        params.append(date_from)
    if date_to:
        where_clauses.append('received_at <= ?')
        params.append(date_to)
    
    where_sql = ' AND '.join(where_clauses) if where_clauses else '1=1'
    
    try:
        cursor.execute(f'SELECT COUNT(*) FROM signals WHERE {where_sql}', params)
        total_count = cursor.fetchone()[0]
        
        cursor.execute(f'''
            SELECT s.*, c.name as channel_name
            FROM signals s
            LEFT JOIN channels c ON s.channel_id = c.discord_channel_id OR s.channel_id = CAST(c.id AS TEXT)
            WHERE {where_sql}
            ORDER BY s.received_at DESC
            LIMIT ? OFFSET ?
        ''', params + [limit, offset])
        
        rows = cursor.fetchall()
        signals = []
        for row in rows:
            signal = dict(row)
            for key in ['received_at', 'detected_at', 'validated_at', 'submitted_at', 'executed_at']:
                if key in signal and signal[key] is not None:
                    if hasattr(signal[key], 'isoformat'):
                        signal[key] = signal[key].isoformat()
            signals.append(signal)
        
        return signals, total_count
    except Exception as e:
        print(f"[DATABASE] Error getting signal history: {e}")
        import traceback
        traceback.print_exc()
        return [], 0


def get_signal_transitions(signal_id: int) -> List[Dict]:
    """Get all transitions for a signal (audit trail)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT * FROM signal_event_transitions
            WHERE signal_id = ?
            ORDER BY created_at ASC
        ''', (signal_id,))
        
        rows = cursor.fetchall()
        transitions = []
        for row in rows:
            t = dict(row)
            if 'created_at' in t and t['created_at'] is not None:
                if hasattr(t['created_at'], 'isoformat'):
                    t['created_at'] = t['created_at'].isoformat()
            transitions.append(t)
        return transitions
    except Exception as e:
        print(f"[DATABASE] Error getting signal transitions: {e}")
        return []


def get_signal_statistics(market: str = None, days: int = 7) -> Dict[str, Any]:
    """Get signal statistics for dashboard"""
    conn = get_connection()
    cursor = conn.cursor()
    
    market_filter = ''
    params = []
    if market:
        market_filter = 'AND market = ?'
        params.append(market)
    
    try:
        cursor.execute(f'''
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN execution_status = 'EXECUTED' THEN 1 ELSE 0 END) as executed,
                SUM(CASE WHEN execution_status = 'REJECTED' THEN 1 ELSE 0 END) as rejected,
                SUM(CASE WHEN execution_status = 'FAILED' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN execution_status = 'VALIDATED' THEN 1 ELSE 0 END) as validated,
                SUM(CASE WHEN execution_status = 'DETECTED' THEN 1 ELSE 0 END) as detected,
                AVG(pnl_percent) as avg_pnl_percent,
                SUM(pnl_realized) as total_pnl
            FROM signals
            WHERE received_at >= datetime('now', '-{days} days') {market_filter}
        ''', params)
        
        row = cursor.fetchone()
        stats = dict(row) if row else {}
        
        cursor.execute(f'''
            SELECT broker_target, COUNT(*) as count
            FROM signals
            WHERE received_at >= datetime('now', '-{days} days') 
            AND broker_target IS NOT NULL {market_filter}
            GROUP BY broker_target
        ''', params)
        
        broker_stats = {row['broker_target']: row['count'] for row in cursor.fetchall()}
        stats['by_broker'] = broker_stats
        
        cursor.execute(f'''
            SELECT execution_status, last_error, COUNT(*) as count
            FROM signals
            WHERE received_at >= datetime('now', '-{days} days')
            AND execution_status IN ('REJECTED', 'FAILED') {market_filter}
            GROUP BY execution_status, last_error
            ORDER BY count DESC
            LIMIT 10
        ''', params)
        
        stats['rejection_reasons'] = [dict(row) for row in cursor.fetchall()]
        
        return stats
    except Exception as e:
        print(f"[DATABASE] Error getting signal statistics: {e}")
        return {}


def get_signal_by_id(signal_id: int) -> Optional[Dict]:
    """Get a single signal by ID with full details"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT s.*, c.name as channel_name
            FROM signals s
            LEFT JOIN channels c ON s.channel_id = c.discord_channel_id OR s.channel_id = CAST(c.id AS TEXT)
            WHERE s.id = ?
        ''', (signal_id,))
        
        row = cursor.fetchone()
        if row:
            signal = dict(row)
            for key in ['received_at', 'detected_at', 'validated_at', 'submitted_at', 'executed_at']:
                if key in signal and signal[key] is not None:
                    if hasattr(signal[key], 'isoformat'):
                        signal[key] = signal[key].isoformat()
            signal['transitions'] = get_signal_transitions(signal_id)
            return signal
        return None
    except Exception as e:
        print(f"[DATABASE] Error getting signal by ID: {e}")
        return None


# ==================== FILLED ORDERS ====================

def insert_filled_order(broker: str, broker_order_id: str, symbol: str, side: str,
                        quantity: int, filled_price: float, filled_at: str,
                        asset_type: str = 'option', total_cost: float = None,
                        fees: float = 0, strike: float = None, expiry: str = None,
                        option_type: str = None, channel_id: str = None,
                        signal_id: int = None, trade_id: int = None) -> Optional[int]:
    """Insert a filled order from broker sync. Returns order ID or None if duplicate."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO filled_orders (
                broker, broker_order_id, symbol, asset_type, side, quantity,
                filled_price, total_cost, fees, filled_at, strike, expiry,
                option_type, channel_id, signal_id, trade_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (broker, broker_order_id, symbol, asset_type, side, quantity,
              filled_price, total_cost, fees, filled_at, strike, expiry,
              option_type, channel_id, signal_id, trade_id))
        conn.commit()
        
        if cursor.rowcount > 0:
            return cursor.lastrowid
        return None
    except Exception as e:
        print(f"[DATABASE] Error inserting filled order: {e}")
        return None


def get_filled_orders(broker: str = None, symbol: str = None, 
                      days: int = 7, limit: int = 100) -> List[Dict[str, Any]]:
    """Get filled orders with optional filters."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Use created_at for date filtering (ISO format), not filled_at (may have non-ISO format)
        conditions = [f"created_at >= datetime('now', '-{days} days')"]
        params = []
        
        if broker:
            conditions.append("broker = ?")
            params.append(broker)
        if symbol:
            conditions.append("symbol LIKE ?")
            params.append(f"%{symbol}%")
        
        where_clause = " AND ".join(conditions)
        
        cursor.execute(f'''
            SELECT * FROM filled_orders
            WHERE {where_clause}
            ORDER BY id DESC
            LIMIT ?
        ''', params + [limit])
        
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"[DATABASE] Error getting filled orders: {e}")
        return []


def get_broker_sync_state(broker: str) -> Optional[Dict[str, Any]]:
    """Get the last sync state for a broker."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT * FROM broker_sync_state WHERE broker = ?', (broker,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DATABASE] Error getting broker sync state: {e}")
        return None


def update_broker_sync_state(broker: str, last_sync_at: str = None,
                              last_order_id: str = None, sync_cursor: str = None,
                              error: str = None):
    """Update the sync state for a broker."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        if error:
            cursor.execute('''
                INSERT INTO broker_sync_state (broker, last_error, error_count, updated_at)
                VALUES (?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(broker) DO UPDATE SET
                    last_error = ?,
                    error_count = error_count + 1,
                    updated_at = CURRENT_TIMESTAMP
            ''', (broker, error, error))
        else:
            cursor.execute('''
                INSERT INTO broker_sync_state (broker, last_sync_at, last_order_id, sync_cursor, error_count, updated_at)
                VALUES (?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
                ON CONFLICT(broker) DO UPDATE SET
                    last_sync_at = COALESCE(?, last_sync_at),
                    last_order_id = COALESCE(?, last_order_id),
                    sync_cursor = COALESCE(?, sync_cursor),
                    error_count = 0,
                    last_error = NULL,
                    updated_at = CURRENT_TIMESTAMP
            ''', (broker, last_sync_at, last_order_id, sync_cursor,
                  last_sync_at, last_order_id, sync_cursor))
        conn.commit()
    except Exception as e:
        print(f"[DATABASE] Error updating broker sync state: {e}")


def get_filled_orders_count(broker: str = None, symbol: str = None, days: int = 1) -> int:
    """Get count of filled orders for stats."""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        conditions = [f"filled_at >= datetime('now', '-{days} days')"]
        params = []
        
        if broker:
            conditions.append("broker = ?")
            params.append(broker)
        if symbol:
            conditions.append("symbol LIKE ?")
            params.append(f"%{symbol}%")
        
        where_clause = " AND ".join(conditions)
        
        cursor.execute(f'''
            SELECT COUNT(*) FROM filled_orders
            WHERE {where_clause}
        ''', params)
        
        return cursor.fetchone()[0]
    except Exception as e:
        print(f"[DATABASE] Error getting filled orders count: {e}")
        return 0


# Initialize tables
init_channel_messages_table()
init_signal_formats_table()
init_conditional_orders_table()
migrate_channels_for_conditional_orders()
migrate_trades_for_conditional_orders()
init_conditional_order_settings()
init_upstox_pending_orders_table()
init_upstox_settings()

init_db()
