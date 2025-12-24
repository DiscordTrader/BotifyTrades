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
    """Get database file path"""
    return Path.cwd() / 'bot_data.db'


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
    
    # Create indexes for license tables
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_server_licenses_key ON server_licenses(license_key)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_server_licenses_machine ON server_licenses(machine_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_server_licenses_status ON server_licenses(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_server_trials_machine ON server_trials(machine_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_server_machines_license ON server_machines(license_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_license_log_key ON license_validation_log(license_key)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_license_log_time ON license_validation_log(created_at)')
    
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
    
    # Create GUI_EXEC channel for tracking GUI-originated trades (if not exists)
    cursor.execute("""
        INSERT OR IGNORE INTO channels (discord_channel_id, name, category, execute_enabled, track_enabled, is_active)
        VALUES ('GUI_EXEC', 'GUI Executions', 'EXECUTE', 1, 1, 1)
    """)
    if cursor.rowcount > 0:
        print("[DATABASE] ✓ Created GUI_EXEC channel for options page tracking")
    
    conn.commit()
    print("[DATABASE] ✓ Database initialized")

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


# Channel management functions
def add_channel(discord_channel_id: str, name: str, category: str = None, execute_enabled: int = 0, track_enabled: int = 0, broker_override: Optional[str] = None, enabled_brokers = None):
    """Add a new channel with dual-mode and multi-broker support"""
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
    
    try:
        cursor.execute('''
            INSERT INTO channels (discord_channel_id, name, category, execute_enabled, track_enabled, broker_override, enabled_brokers)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (discord_channel_id, name, category, execute_enabled, track_enabled, broker_override, enabled_brokers))
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None  # Channel already exists


def get_channels(category: Optional[str] = None) -> List[Dict]:
    """Get all channels or filter by category/flags with signal statistics"""
    conn = get_connection()
    cursor = conn.cursor()
    
    if category == 'EXECUTE':
        # Show channels with execute_enabled=1
        cursor.execute('SELECT * FROM channels WHERE execute_enabled = 1 ORDER BY name')
    elif category == 'TRACK':
        # Show channels with track_enabled=1
        cursor.execute('SELECT * FROM channels WHERE track_enabled = 1 ORDER BY name')
    elif category:
        # Fallback to old category filtering for backwards compatibility
        cursor.execute('SELECT * FROM channels WHERE category = ? ORDER BY name', (category,))
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
               created_at, updated_at, default_quantity
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
        'default_quantity': row[20]
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
               created_at, updated_at, default_quantity
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
        'default_quantity': row[20]
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
                   'stop_loss_pct', 'trailing_stop_pct', 'trailing_activation_pct', 'enabled_brokers', 'position_size_pct', 'tracking_position_size_pct',
                   'default_quantity', 'risk_management_enabled']:
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
    elif 'execute_enabled' in kwargs and 'category' not in kwargs:
        # If execute_enabled is being set, update category accordingly
        if kwargs['execute_enabled'] == 1:
            fields.append("category = ?")
            values.append('EXECUTE')
        elif 'track_enabled' in kwargs and kwargs['track_enabled'] == 1:
            fields.append("category = ?")
            values.append('TRACK')
    elif 'track_enabled' in kwargs and kwargs['track_enabled'] == 1 and 'category' not in kwargs:
        # If track_enabled is being set and execute_enabled is not, set category to TRACK
        if 'execute_enabled' not in kwargs or kwargs['execute_enabled'] == 0:
            fields.append("category = ?")
            values.append('TRACK')
    
    if fields:
        values.append(datetime.now())
        values.append(channel_id)
        query = f"UPDATE channels SET {', '.join(fields)}, updated_at = ? WHERE id = ?"
        cursor.execute(query, values)
        conn.commit()


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
    """Add a new trade to the database"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO trades (
            channel_id, message_id, direction, asset_type, symbol,
            strike, expiry, call_put, quantity, intended_price,
            executed_price, executed_at, status, broker, order_id,
            stop_loss_price, profit_target_price, risk_trigger, origin_trade_id,
            user_id, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        signal_data.get('intended_price'),
        signal_data.get('executed_price'),
        datetime.now() if signal_data.get('executed') else None,
        signal_data.get('status', 'PENDING'),
        signal_data.get('broker'),
        signal_data.get('order_id'),
        signal_data.get('stop_loss_price'),
        signal_data.get('profit_target_price'),
        signal_data.get('risk_trigger'),
        signal_data.get('origin_trade_id'),
        signal_data.get('user_id'),
        signal_data.get('source', 'discord')
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
        query += ' AND t.broker = ?'
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


def close_lot(lot_id: int, channel_id: int, signal_id: int, close_qty: int, close_price: float, closed_at):
    """Close a lot (fully or partially) and record PNL"""
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
            closed_at, pnl, pnl_percent, holding_days, author_name, user_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (lot_id, channel_id, signal_id, close_qty, close_price, closed_at, pnl, pnl_percent, holding_days, author_name, user_id))
    
    # Update lot status
    new_remaining = lot['remaining_qty'] - close_qty
    if new_remaining <= 0:
        cursor.execute('UPDATE signal_lots SET remaining_qty = 0, status = "CLOSED" WHERE id = ?', (lot_id,))
    else:
        cursor.execute('UPDATE signal_lots SET remaining_qty = ?, status = "PARTIAL" WHERE id = ?', (new_remaining, lot_id))
    
    conn.commit()
    return cursor.lastrowid


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
def add_signal(discord_channel_id: str, message_id: str, signal_type: str, symbol: str, quantity: int, price: float = None, asset_type: str = 'stock', author_name: str = None, strike: float = None, expiry: str = None, call_put: str = None):
    """Add a new signal to the database with author attribution and option details"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get channel internal ID
    cursor.execute('SELECT id FROM channels WHERE discord_channel_id = ?', (discord_channel_id,))
    channel = cursor.fetchone()
    channel_id = channel['id'] if channel else None
    
    try:
        cursor.execute('''
            INSERT INTO signals (
                channel_id, message_id, direction, asset_type, symbol,
                quantity, price, strike, expiry, call_put, author_name, received_at, executed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 0)
        ''', (channel_id, message_id, signal_type, asset_type, symbol, quantity, price, strike, expiry, call_put, author_name))
        
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


def get_channel_leaderboard(time_period='all', start_date=None, end_date=None):
    """
    Get channel performance leaderboard with TQS scoring.
    
    Args:
        time_period: 'today', '7d', '30d', 'year', 'all', or 'custom'
        start_date: For custom period (YYYY-MM-DD)
        end_date: For custom period (YYYY-MM-DD)
    
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
    
    # Build date filter SQL
    date_filter = ""
    date_params = []
    if date_start and date_end:
        date_filter = "AND lc.closed_at >= ? AND lc.closed_at <= ?"
        date_params = [date_start, date_end]
    
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
            
            -- Cost basis: multiply by 100 only for options, not stocks
            COALESCE(SUM(sl.open_price * lc.closed_qty * CASE WHEN sl.asset_type = 'option' THEN 100 ELSE 1 END), 0) as total_cost_basis,
            
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
        WHERE c.is_active = 1 {date_filter}
        GROUP BY c.id, c.name, c.discord_channel_id
        HAVING COUNT(DISTINCT lc.id) > 0
    '''
    
    cursor.execute(query, date_params)
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


# ============ TRADING SETTINGS ============

def get_trading_settings() -> Dict[str, Any]:
    """Get trading settings"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT max_position_size, updated_at, global_default_quantity, max_position_size_enabled
        FROM trading_settings
        WHERE id = 1
    ''')
    
    row = cursor.fetchone()
    if row:
        return {
            'max_position_size': int(row['max_position_size']),
            'updated_at': row['updated_at'],
            'global_default_quantity': row['global_default_quantity'],
            'max_position_size_enabled': bool(row['max_position_size_enabled']) if row['max_position_size_enabled'] is not None else True
        }
    
    return {
        'max_position_size': 600,
        'updated_at': None,
        'global_default_quantity': None,
        'max_position_size_enabled': True
    }


def update_trading_settings(max_position_size: int, global_default_quantity: int = None, max_position_size_enabled: bool = True) -> bool:
    """Update trading settings"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE trading_settings
            SET max_position_size = ?,
                global_default_quantity = ?,
                max_position_size_enabled = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''', (int(max_position_size), global_default_quantity, 1 if max_position_size_enabled else 0))
        
        conn.commit()
        return True
    except Exception as e:
        print(f"[DATABASE] Error updating trading settings: {e}")
        return False


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
        return settings
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
    """Create channel_mappings table if it doesn't exist - now maps source channels to webhook URLs"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS channel_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_channel_id TEXT NOT NULL,
            source_channel_name TEXT DEFAULT '',
            webhook_url TEXT NOT NULL,
            webhook_name TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_channel_id, webhook_url)
        )
    ''')
    cursor.execute('''
        ALTER TABLE channel_mappings ADD COLUMN webhook_url TEXT DEFAULT ''
    ''') if False else None
    cursor.execute('''
        ALTER TABLE channel_mappings ADD COLUMN webhook_name TEXT DEFAULT ''
    ''') if False else None
    conn.commit()
    print("[DATABASE] ✓ Channel mappings table ready")


def migrate_channel_mappings_to_webhook():
    """Migrate old channel_mappings table to new webhook-based structure"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("PRAGMA table_info(channel_mappings)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'destination_channel_id' in columns or 'webhook_url' not in columns:
            print("[DATABASE] Detected old channel_mappings schema, recreating table...")
            cursor.execute('DROP TABLE IF EXISTS channel_mappings')
            conn.commit()
            init_channel_mappings_table()
            print("[DATABASE] ✓ Recreated channel_mappings table with webhook URL support")
            return
        
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='channel_mappings'")
        result = cursor.fetchone()
        if result:
            schema = result[0] if result[0] else ''
            has_old_constraint = 'UNIQUE(source_channel_id)' in schema and 'UNIQUE(source_channel_id, webhook_url)' not in schema
            if has_old_constraint:
                print("[DATABASE] Detected old unique constraint, recreating table...")
                cursor.execute('DROP TABLE IF EXISTS channel_mappings')
                conn.commit()
                init_channel_mappings_table()
                print("[DATABASE] ✓ Recreated channel_mappings table with correct schema")
            
    except Exception as e:
        print(f"[DATABASE] Migration skipped or error: {e}")


def get_channel_mappings() -> List[Dict[str, Any]]:
    """Get all channel mappings"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        init_channel_mappings_table()
        migrate_channel_mappings_to_webhook()
        
        cursor.execute('''
            SELECT id, source_channel_id, source_channel_name, 
                   COALESCE(webhook_url, '') as webhook_url, 
                   COALESCE(webhook_name, '') as webhook_name, 
                   is_active, created_at, updated_at
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


def add_channel_mapping(source_channel_id: str, webhook_url: str,
                        source_channel_name: str = '', webhook_name: str = '') -> Dict[str, Any]:
    """Add a new channel mapping (source channel -> webhook URL)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        init_channel_mappings_table()
        migrate_channel_mappings_to_webhook()
        
        cursor.execute('''
            INSERT INTO channel_mappings (source_channel_id, source_channel_name, 
                                          webhook_url, webhook_name)
            VALUES (?, ?, ?, ?)
        ''', (source_channel_id.strip(), source_channel_name.strip(), 
              webhook_url.strip(), webhook_name.strip()))
        
        mapping_id = cursor.lastrowid
        conn.commit()
        print(f"[DATABASE] ✓ Added channel mapping: {source_channel_id} -> {webhook_url[:50]}...")
        
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
                           is_active: bool = None) -> Dict[str, Any]:
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
    """Get all active webhook URLs from channel_mappings for Trade Monitor broadcasting"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        init_channel_mappings_table()
        cursor.execute('''
            SELECT DISTINCT webhook_url, webhook_name
            FROM channel_mappings
            WHERE is_active = 1 AND webhook_url IS NOT NULL AND webhook_url != ''
        ''')
        
        rows = cursor.fetchall()
        return [{'webhook_url': row['webhook_url'], 'webhook_name': row['webhook_name'] or 'Unnamed'} for row in rows]
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
            ('CA', 'questrade', 'Questrade', '["refresh_token"]', 'qtrade', 1, 1, 0, '30-min access / 3-day refresh', 1),
            ('IN', 'upstox', 'Upstox', '["api_key","api_secret","redirect_uri","access_token"]', 'upstox-python-sdk', 1, 1, 0, '1 day', 1),
            ('IN', 'zerodha', 'Zerodha (Kite)', '["api_key","api_secret","user_id","password","totp_secret"]', 'kiteconnect', 1, 1, 0, 'Daily 6 AM IST', 2),
            ('IN', 'dhan', 'Dhan', '["client_id","access_token"]', 'dhanhq', 1, 1, 0, '24 hours', 3)
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


# Initialize tables
init_channel_messages_table()
init_signal_formats_table()

init_db()
