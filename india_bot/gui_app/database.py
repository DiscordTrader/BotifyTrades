"""
India Bot Database Module
SQLite database for India market trading bot
Extracted from main BotifyTrades project
"""

import sqlite3
import os
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), 'india_bot.db')

@contextmanager
def get_db_connection():
    """Get database connection with context manager"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_database():
    """Initialize India bot database with required tables"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS broker_credentials (
                broker_name TEXT PRIMARY KEY,
                credentials TEXT,
                is_connected INTEGER DEFAULT 0,
                connection_status TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS telegram_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT UNIQUE NOT NULL,
                name TEXT,
                enabled INTEGER DEFAULT 1,
                execute_trades INTEGER DEFAULT 1,
                track_performance INTEGER DEFAULT 1,
                broker_override TEXT,
                enabled_brokers TEXT,
                default_quantity INTEGER DEFAULT 1,
                exit_mode TEXT DEFAULT 'signal',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS india_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT,
                message_id TEXT,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                asset_type TEXT DEFAULT 'option',
                strike REAL,
                expiry TEXT,
                call_put TEXT,
                quantity INTEGER DEFAULT 1,
                lots INTEGER DEFAULT 1,
                price REAL,
                status TEXT DEFAULT 'PENDING',
                broker TEXT,
                order_id TEXT,
                executed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS india_conditional_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                strike REAL,
                expiry TEXT,
                opt_type TEXT,
                trigger_type TEXT NOT NULL,
                trigger_direction TEXT DEFAULT 'OVER',
                trigger_price REAL NOT NULL,
                current_price REAL,
                status TEXT DEFAULT 'PENDING',
                broker TEXT,
                channel_id TEXT,
                channel_name TEXT,
                lots INTEGER DEFAULT 1,
                quantity INTEGER,
                stop_loss REAL,
                targets TEXT,
                action TEXT DEFAULT 'BTO',
                order_id TEXT,
                error_message TEXT,
                signal_id INTEGER,
                message_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                triggered_at TIMESTAMP,
                executed_at TIMESTAMP,
                cancelled_at TIMESTAMP,
                last_price_update TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS india_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                strike REAL,
                expiry TEXT,
                opt_type TEXT,
                quantity INTEGER NOT NULL,
                lots INTEGER,
                entry_price REAL,
                current_price REAL,
                pnl REAL,
                broker TEXT NOT NULL,
                channel_id TEXT,
                status TEXT DEFAULT 'OPEN',
                opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_at TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS upstox_pending_orders (
                pending_order_id TEXT PRIMARY KEY,
                signal_data TEXT NOT NULL,
                status TEXT DEFAULT 'PENDING',
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                broker_order_id TEXT,
                error_message TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS zerodha_pending_orders (
                pending_order_id TEXT PRIMARY KEY,
                signal_data TEXT NOT NULL,
                status TEXT DEFAULT 'PENDING',
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                broker_order_id TEXT,
                error_message TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS dhanq_pending_orders (
                pending_order_id TEXT PRIMARY KEY,
                signal_data TEXT NOT NULL,
                status TEXT DEFAULT 'PENDING',
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                broker_order_id TEXT,
                error_message TEXT
            )
        ''')
        
        conn.commit()
        print("[DATABASE] ✓ India bot database initialized")

def get_broker_credentials(broker_name: str) -> Optional[Dict[str, Any]]:
    """Get broker credentials"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT credentials FROM broker_credentials WHERE broker_name = ?', (broker_name,))
        row = cursor.fetchone()
        if row and row['credentials']:
            return json.loads(row['credentials'])
    return None

def save_broker_credentials(broker_name: str, credentials: Dict[str, Any]):
    """Save broker credentials"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO broker_credentials (broker_name, credentials, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', (broker_name, json.dumps(credentials)))
        conn.commit()

def update_broker_connection_status(broker_name: str, is_connected: bool, status_message: str = None):
    """Update broker connection status"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE broker_credentials 
            SET is_connected = ?, connection_status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE broker_name = ?
        ''', (1 if is_connected else 0, status_message, broker_name))
        conn.commit()

def get_telegram_channels() -> List[Dict[str, Any]]:
    """Get all Telegram channels"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM telegram_channels WHERE enabled = 1')
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def get_channel_settings(chat_id: str) -> Optional[Dict[str, Any]]:
    """Get settings for a specific channel"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM telegram_channels WHERE chat_id = ?', (str(chat_id),))
        row = cursor.fetchone()
        if row:
            result = dict(row)
            if result.get('enabled_brokers'):
                result['enabled_brokers'] = json.loads(result['enabled_brokers'])
            return result
    return None

def save_signal(signal: Dict[str, Any]) -> int:
    """Save a signal to database"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO india_signals 
            (channel_id, message_id, symbol, action, asset_type, strike, expiry, call_put, quantity, lots, price, broker)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            signal.get('channel_id'),
            signal.get('message_id'),
            signal.get('symbol'),
            signal.get('action'),
            signal.get('asset', 'option'),
            signal.get('strike'),
            signal.get('expiry'),
            signal.get('opt_type'),
            signal.get('qty', 1),
            signal.get('lots', 1),
            signal.get('price'),
            signal.get('broker')
        ))
        conn.commit()
        return cursor.lastrowid

def get_conditional_orders(status: str = None) -> List[Dict[str, Any]]:
    """Get conditional orders"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if status:
            cursor.execute('SELECT * FROM india_conditional_orders WHERE status = ? ORDER BY created_at DESC', (status,))
        else:
            cursor.execute('SELECT * FROM india_conditional_orders ORDER BY created_at DESC')
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def create_conditional_order(order: Dict[str, Any]) -> int:
    """Create a conditional order with full audit trail"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO india_conditional_orders 
            (symbol, strike, expiry, opt_type, trigger_type, trigger_direction, trigger_price, 
             broker, channel_id, channel_name, lots, quantity, stop_loss, targets, action,
             signal_id, message_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            order.get('symbol'),
            order.get('strike'),
            order.get('expiry'),
            order.get('opt_type'),
            order.get('trigger_type'),
            order.get('trigger_direction', 'OVER'),
            order.get('trigger_price'),
            order.get('broker'),
            order.get('channel_id'),
            order.get('channel_name'),
            order.get('lots', 1),
            order.get('quantity'),
            order.get('stop_loss'),
            json.dumps(order.get('targets', [])),
            order.get('action', 'BTO'),
            order.get('signal_id'),
            order.get('message_id')
        ))
        conn.commit()
        return cursor.lastrowid

def update_conditional_order(order_id: int, updates: Dict[str, Any]):
    """Update a conditional order"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        set_parts = []
        values = []
        for key, value in updates.items():
            set_parts.append(f"{key} = ?")
            values.append(value)
        values.append(order_id)
        cursor.execute(f'UPDATE india_conditional_orders SET {", ".join(set_parts)} WHERE id = ?', values)
        conn.commit()

def get_setting(key: str, default: Any = None) -> Any:
    """Get a setting value"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
        row = cursor.fetchone()
        if row:
            return row['value']
    return default

def set_setting(key: str, value: Any):
    """Set a setting value"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', (key, str(value)))
        conn.commit()

def save_upstox_pending_order(order: Dict[str, Any]) -> bool:
    """Save a pending Upstox order"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO upstox_pending_orders 
                (pending_order_id, signal_data, status, reason)
                VALUES (?, ?, 'PENDING', ?)
            ''', (
                order.get('pending_order_id'),
                json.dumps(order.get('signal_data', {})),
                order.get('reason')
            ))
            conn.commit()
            return True
    except Exception as e:
        print(f"[DATABASE] Error saving pending order: {e}")
        return False

def get_upstox_pending_orders(status: str = 'PENDING') -> List[Dict[str, Any]]:
    """Get pending Upstox orders"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM upstox_pending_orders WHERE status = ?', (status,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def save_zerodha_pending_order(order: Dict[str, Any]) -> bool:
    """Save a pending Zerodha order"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO zerodha_pending_orders 
                (pending_order_id, signal_data, status, reason)
                VALUES (?, ?, 'PENDING', ?)
            ''', (
                order.get('pending_order_id'),
                json.dumps(order.get('signal_data', {})),
                order.get('reason')
            ))
            conn.commit()
            return True
    except Exception as e:
        print(f"[DATABASE] Error saving Zerodha pending order: {e}")
        return False

def get_zerodha_pending_orders(status: str = 'PENDING') -> List[Dict[str, Any]]:
    """Get pending Zerodha orders"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM zerodha_pending_orders WHERE status = ?', (status,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def update_zerodha_pending_order_status(pending_order_id: str, status: str, broker_order_id: str = None, error_message: str = None):
    """Update a Zerodha pending order status"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if broker_order_id:
            cursor.execute('''
                UPDATE zerodha_pending_orders 
                SET status = ?, broker_order_id = ?, processed_at = CURRENT_TIMESTAMP
                WHERE pending_order_id = ?
            ''', (status, broker_order_id, pending_order_id))
        elif error_message:
            cursor.execute('''
                UPDATE zerodha_pending_orders 
                SET status = ?, error_message = ?, processed_at = CURRENT_TIMESTAMP
                WHERE pending_order_id = ?
            ''', (status, error_message, pending_order_id))
        else:
            cursor.execute('''
                UPDATE zerodha_pending_orders 
                SET status = ?, processed_at = CURRENT_TIMESTAMP
                WHERE pending_order_id = ?
            ''', (status, pending_order_id))
        conn.commit()

def save_dhanq_pending_order(order: Dict[str, Any]) -> bool:
    """Save a pending DhanQ order"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO dhanq_pending_orders 
                (pending_order_id, signal_data, status, reason)
                VALUES (?, ?, 'PENDING', ?)
            ''', (
                order.get('pending_order_id'),
                json.dumps(order.get('signal_data', {})),
                order.get('reason')
            ))
            conn.commit()
            return True
    except Exception as e:
        print(f"[DATABASE] Error saving DhanQ pending order: {e}")
        return False

def get_dhanq_pending_orders(status: str = 'PENDING') -> List[Dict[str, Any]]:
    """Get pending DhanQ orders"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM dhanq_pending_orders WHERE status = ?', (status,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def update_dhanq_pending_order_status(pending_order_id: str, status: str, broker_order_id: str = None, error_message: str = None):
    """Update a DhanQ pending order status"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if broker_order_id:
            cursor.execute('''
                UPDATE dhanq_pending_orders 
                SET status = ?, broker_order_id = ?, processed_at = CURRENT_TIMESTAMP
                WHERE pending_order_id = ?
            ''', (status, broker_order_id, pending_order_id))
        elif error_message:
            cursor.execute('''
                UPDATE dhanq_pending_orders 
                SET status = ?, error_message = ?, processed_at = CURRENT_TIMESTAMP
                WHERE pending_order_id = ?
            ''', (status, error_message, pending_order_id))
        else:
            cursor.execute('''
                UPDATE dhanq_pending_orders 
                SET status = ?, processed_at = CURRENT_TIMESTAMP
                WHERE pending_order_id = ?
            ''', (status, pending_order_id))
        conn.commit()

def update_upstox_pending_order_status(pending_order_id: str, status: str, broker_order_id: str = None, error_message: str = None):
    """Update an Upstox pending order status"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if broker_order_id:
            cursor.execute('''
                UPDATE upstox_pending_orders 
                SET status = ?, broker_order_id = ?, processed_at = CURRENT_TIMESTAMP
                WHERE pending_order_id = ?
            ''', (status, broker_order_id, pending_order_id))
        elif error_message:
            cursor.execute('''
                UPDATE upstox_pending_orders 
                SET status = ?, error_message = ?, processed_at = CURRENT_TIMESTAMP
                WHERE pending_order_id = ?
            ''', (status, error_message, pending_order_id))
        else:
            cursor.execute('''
                UPDATE upstox_pending_orders 
                SET status = ?, processed_at = CURRENT_TIMESTAMP
                WHERE pending_order_id = ?
            ''', (status, pending_order_id))
        conn.commit()

init_database()
