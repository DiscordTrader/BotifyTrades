"""
Webhook Service for posting trading signals to Discord with P&L tracking.
Supports BTO (Buy to Open) and STC (Sell to Close) signals with:
- Real-time P&L calculation
- Trade summaries
- Partial exit handling
"""

import requests
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
import os
import logging

from gui_app.database import get_db_path

logger = logging.getLogger(__name__)


def get_db_connection():
    """Get database connection with timeout and WAL mode."""
    conn = sqlite3.connect(get_db_path(), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=30000')
    except Exception:
        pass
    return conn


def init_webhook_tables():
    """Initialize webhook-related database tables."""
    print(f"[WEBHOOK] Initializing webhook tables at: {get_db_path()}")
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS webhook_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            strike REAL,
            expiry TEXT,
            call_put TEXT,
            original_qty INTEGER NOT NULL,
            remaining_qty INTEGER NOT NULL,
            entry_price REAL NOT NULL,
            opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'OPEN' CHECK(status IN ('OPEN', 'CLOSED')),
            trade_type TEXT DEFAULT 'swing',
            webhook_url TEXT,
            UNIQUE(symbol, strike, expiry, call_put, status) ON CONFLICT IGNORE
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS webhook_closures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id INTEGER NOT NULL,
            close_qty INTEGER NOT NULL,
            close_price REAL NOT NULL,
            pnl_dollars REAL NOT NULL,
            pnl_percent REAL NOT NULL,
            closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (position_id) REFERENCES webhook_positions(id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS webhook_config (
            id INTEGER PRIMARY KEY,
            webhook_url TEXT,
            bot_name TEXT DEFAULT '',
            avatar_url TEXT,
            enabled INTEGER DEFAULT 1,
            auto_post_bto INTEGER DEFAULT 0,
            auto_post_stc INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS webhook_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            webhook_url TEXT NOT NULL,
            bot_name TEXT DEFAULT '',
            avatar_url TEXT,
            color TEXT DEFAULT '#FF6B35',
            enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('SELECT COUNT(*) FROM webhook_config')
    if cursor.fetchone()[0] == 0:
        cursor.execute('''
            INSERT INTO webhook_config (id, webhook_url, bot_name, enabled)
            VALUES (1, '', '', 1)
        ''')
    
    conn.commit()
    conn.close()


def get_webhook_config() -> Dict[str, Any]:
    """Get webhook configuration."""
    init_webhook_tables()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM webhook_config WHERE id = 1')
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    return {
        'webhook_url': '',
        'bot_name': '',
        'avatar_url': None,
        'enabled': True,
        'auto_post_bto': False,
        'auto_post_stc': False
    }


def save_webhook_config(config: Dict[str, Any]) -> bool:
    """Save webhook configuration."""
    init_webhook_tables()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            UPDATE webhook_config SET
                webhook_url = ?,
                bot_name = ?,
                avatar_url = ?,
                enabled = ?,
                auto_post_bto = ?,
                auto_post_stc = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''', (
            config.get('webhook_url', ''),
            config.get('bot_name', ''),
            config.get('avatar_url'),
            1 if config.get('enabled', True) else 0,
            1 if config.get('auto_post_bto', False) else 0,
            1 if config.get('auto_post_stc', False) else 0
        ))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error saving webhook config: {e}")
        return False
    finally:
        conn.close()


def get_webhook_channels() -> List[Dict[str, Any]]:
    """Get all webhook channels."""
    init_webhook_tables()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM webhook_channels ORDER BY name ASC')
    channels = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return channels


def get_webhook_channel(channel_id: int) -> Optional[Dict[str, Any]]:
    """Get a specific webhook channel by ID."""
    init_webhook_tables()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM webhook_channels WHERE id = ?', (channel_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def add_webhook_channel(name: str, webhook_url: str, bot_name: str = '', color: str = '#FF6B35') -> Dict[str, Any]:
    """Add a new webhook channel."""
    init_webhook_tables()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO webhook_channels (name, webhook_url, bot_name, color, enabled)
            VALUES (?, ?, ?, ?, 1)
        ''', (name, webhook_url, bot_name, color))
        conn.commit()
        channel_id = cursor.lastrowid
        return {'success': True, 'id': channel_id, 'message': f'Channel "{name}" added successfully'}
    except Exception as e:
        logger.error(f"Error adding webhook channel: {e}")
        return {'success': False, 'error': str(e)}
    finally:
        conn.close()


def update_webhook_channel(channel_id: int, name: str = None, webhook_url: str = None, 
                           bot_name: str = None, color: str = None, enabled: bool = None) -> Dict[str, Any]:
    """Update an existing webhook channel."""
    init_webhook_tables()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        updates = []
        params = []
        
        if name is not None:
            updates.append('name = ?')
            params.append(name)
        if webhook_url is not None:
            updates.append('webhook_url = ?')
            params.append(webhook_url)
        if bot_name is not None:
            updates.append('bot_name = ?')
            params.append(bot_name)
        if color is not None:
            updates.append('color = ?')
            params.append(color)
        if enabled is not None:
            updates.append('enabled = ?')
            params.append(1 if enabled else 0)
        
        if not updates:
            return {'success': False, 'error': 'No fields to update'}
        
        updates.append('updated_at = CURRENT_TIMESTAMP')
        params.append(channel_id)
        
        query = f'UPDATE webhook_channels SET {", ".join(updates)} WHERE id = ?'
        cursor.execute(query, params)
        conn.commit()
        
        return {'success': True, 'message': 'Channel updated successfully'}
    except Exception as e:
        logger.error(f"Error updating webhook channel: {e}")
        return {'success': False, 'error': str(e)}
    finally:
        conn.close()


def delete_webhook_channel(channel_id: int) -> Dict[str, Any]:
    """Delete a webhook channel."""
    init_webhook_tables()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('DELETE FROM webhook_channels WHERE id = ?', (channel_id,))
        conn.commit()
        return {'success': True, 'message': 'Channel deleted successfully'}
    except Exception as e:
        logger.error(f"Error deleting webhook channel: {e}")
        return {'success': False, 'error': str(e)}
    finally:
        conn.close()


def normalize_expiry(expiry: str) -> str:
    """Normalize expiry to MM/DD format for consistent storage and matching."""
    if not expiry:
        return ""
    
    expiry = expiry.strip()
    
    if '-' in expiry:
        parts = expiry.split('-')
        if len(parts) == 3:
            return f"{parts[1]}/{parts[2]}"
        elif len(parts) == 2:
            return f"{parts[0]}/{parts[1]}"
    
    return expiry


def format_option_display(symbol: str, strike: float, expiry: str, call_put: str) -> str:
    """Format option for display like: IREN 42C 12/26"""
    cp = 'C' if call_put and call_put.upper().startswith('C') else 'P'
    strike_str = f"{strike:g}" if strike else ""
    
    exp_display = normalize_expiry(expiry)
    
    return f"{symbol} {strike_str}{cp} {exp_display}"


def open_webhook_position(
    symbol: str,
    strike: float,
    expiry: str,
    call_put: str,
    qty: int,
    entry_price: float,
    trade_type: str = 'swing',
    webhook_url: str = None
) -> Optional[int]:
    """Open a new position for webhook P&L tracking."""
    init_webhook_tables()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    normalized_expiry = normalize_expiry(expiry)
    normalized_cp = call_put.upper()[0] if call_put else 'C'
    
    try:
        cursor.execute('''
            SELECT id, remaining_qty FROM webhook_positions 
            WHERE symbol = ? AND strike = ? AND expiry = ? AND call_put = ? AND webhook_url = ? AND status = "OPEN"
        ''', (symbol.upper(), strike, normalized_expiry, normalized_cp, webhook_url or ''))
        existing = cursor.fetchone()
        
        if existing:
            new_qty = existing['remaining_qty'] + qty
            cursor.execute('UPDATE webhook_positions SET remaining_qty = ?, original_qty = original_qty + ? WHERE id = ?',
                          (new_qty, qty, existing['id']))
            conn.commit()
            return existing['id']
        
        cursor.execute('''
            INSERT INTO webhook_positions (symbol, strike, expiry, call_put, original_qty, remaining_qty, entry_price, trade_type, webhook_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (symbol.upper(), strike, normalized_expiry, normalized_cp, qty, qty, entry_price, trade_type, webhook_url or ''))
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        logger.error(f"Error opening webhook position: {e}")
        return None
    finally:
        conn.close()


def close_webhook_position(
    symbol: str,
    strike: float,
    expiry: str,
    call_put: str,
    close_qty: int,
    close_price: float,
    webhook_url: str = None
) -> Optional[Dict[str, Any]]:
    """Close (fully or partially) a webhook position and calculate P&L."""
    init_webhook_tables()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    normalized_expiry = normalize_expiry(expiry)
    normalized_cp = call_put.upper()[0] if call_put else 'C'
    
    try:
        if webhook_url:
            cursor.execute('''
                SELECT * FROM webhook_positions 
                WHERE symbol = ? AND strike = ? AND expiry = ? AND call_put = ? AND webhook_url = ? AND status = "OPEN"
                ORDER BY opened_at ASC
            ''', (symbol.upper(), strike, normalized_expiry, normalized_cp, webhook_url))
            position = cursor.fetchone()
        else:
            cursor.execute('''
                SELECT * FROM webhook_positions 
                WHERE symbol = ? AND strike = ? AND expiry = ? AND call_put = ? AND status = "OPEN"
                ORDER BY opened_at ASC
            ''', (symbol.upper(), strike, normalized_expiry, normalized_cp))
            position = cursor.fetchone()
        
        if not position:
            cursor.execute('''
                SELECT * FROM webhook_positions 
                WHERE symbol = ? AND strike = ? AND call_put = ? AND status = "OPEN"
                ORDER BY opened_at ASC
            ''', (symbol.upper(), strike, normalized_cp))
            position = cursor.fetchone()
        
        if not position:
            return None
        
        position = dict(position)
        entry_price = position['entry_price']
        remaining = position['remaining_qty']
        actual_close_qty = min(close_qty, remaining)
        
        is_stock = position['strike'] == 0 or position['strike'] is None
        
        if is_stock:
            pnl_per_share = close_price - entry_price
            total_pnl = pnl_per_share * actual_close_qty
        else:
            pnl_per_contract = (close_price - entry_price) * 100
            total_pnl = pnl_per_contract * actual_close_qty
        
        pnl_percent = ((close_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
        
        cursor.execute('''
            INSERT INTO webhook_closures (position_id, close_qty, close_price, pnl_dollars, pnl_percent)
            VALUES (?, ?, ?, ?, ?)
        ''', (position['id'], actual_close_qty, close_price, total_pnl, pnl_percent))
        
        new_remaining = remaining - actual_close_qty
        if new_remaining <= 0:
            cursor.execute('UPDATE webhook_positions SET remaining_qty = 0, status = "CLOSED" WHERE id = ?', (position['id'],))
        else:
            cursor.execute('UPDATE webhook_positions SET remaining_qty = ? WHERE id = ?', (new_remaining, position['id']))
        
        conn.commit()
        
        cursor.execute('''
            SELECT SUM(close_qty) as total_closed, 
                   SUM(close_qty * close_price) / SUM(close_qty) as avg_close_price, 
                   SUM(pnl_dollars) as total_pnl
            FROM webhook_closures WHERE position_id = ?
        ''', (position['id'],))
        summary = cursor.fetchone()
        
        return {
            'position_id': position['id'],
            'symbol': position['symbol'],
            'strike': position['strike'],
            'expiry': position['expiry'],
            'call_put': position['call_put'],
            'entry_price': entry_price,
            'close_price': close_price,
            'close_qty': actual_close_qty,
            'pnl_dollars': total_pnl,
            'pnl_percent': pnl_percent,
            'original_qty': position['original_qty'],
            'remaining_qty': new_remaining,
            'total_closed': int(summary['total_closed']) if summary and summary['total_closed'] else actual_close_qty,
            'avg_close_price': float(summary['avg_close_price']) if summary and summary['avg_close_price'] else close_price,
            'total_pnl': float(summary['total_pnl']) if summary and summary['total_pnl'] else total_pnl,
            'is_fully_closed': new_remaining <= 0
        }
    except Exception as e:
        logger.error(f"Error closing webhook position: {e}")
        return None
    finally:
        conn.close()


def get_open_positions() -> List[Dict[str, Any]]:
    """Get all open webhook positions."""
    init_webhook_tables()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM webhook_positions WHERE status = "OPEN" ORDER BY opened_at DESC')
    positions = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return positions


def cancel_webhook_position(
    symbol: str,
    strike: float,
    expiry: str,
    call_put: str,
    qty: int = None
) -> bool:
    """Cancel/remove a webhook position (e.g., when a BTO order is canceled).
    
    If qty is provided and less than total position, removes that qty.
    If qty is None or >= total, removes entire position.
    Returns True if position was found and removed/reduced.
    """
    init_webhook_tables()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    normalized_expiry = normalize_expiry(expiry)
    normalized_cp = call_put.upper()[0] if call_put else 'C'
    
    try:
        cursor.execute('''
            SELECT id, remaining_qty, original_qty FROM webhook_positions 
            WHERE symbol = ? AND strike = ? AND expiry = ? AND call_put = ? AND status = "OPEN"
            ORDER BY opened_at DESC LIMIT 1
        ''', (symbol.upper(), strike, normalized_expiry, normalized_cp))
        position = cursor.fetchone()
        
        if not position:
            return False
        
        pos_id = position['id']
        remaining = position['remaining_qty']
        original = position['original_qty']
        
        if qty is None or qty >= remaining:
            # Remove entire position
            cursor.execute('UPDATE webhook_positions SET status = "CANCELED", remaining_qty = 0 WHERE id = ?', (pos_id,))
            logger.info(f"Canceled entire position {pos_id} for {symbol} {strike}{normalized_cp} {normalized_expiry}")
        else:
            # Reduce position qty
            new_remaining = remaining - qty
            new_original = original - qty
            cursor.execute('UPDATE webhook_positions SET remaining_qty = ?, original_qty = ? WHERE id = ?', 
                          (new_remaining, new_original, pos_id))
            logger.info(f"Reduced position {pos_id} by {qty}, new remaining: {new_remaining}")
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error canceling webhook position: {e}")
        return False
    finally:
        conn.close()


def find_matching_position(symbol: str, strike: float = None, expiry: str = None, call_put: str = None) -> Optional[Dict[str, Any]]:
    """Find a matching open position for STC."""
    init_webhook_tables()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = 'SELECT * FROM webhook_positions WHERE symbol = ? AND status = "OPEN"'
    params = [symbol.upper()]
    
    if strike is not None:
        query += ' AND strike = ?'
        params.append(strike)
    if expiry:
        normalized_expiry = normalize_expiry(expiry)
        query += ' AND expiry = ?'
        params.append(normalized_expiry)
    if call_put:
        normalized_cp = call_put.upper()[0] if call_put else 'C'
        query += ' AND call_put = ?'
        params.append(normalized_cp)
    
    query += ' ORDER BY opened_at ASC LIMIT 1'
    
    cursor.execute(query, params)
    row = cursor.fetchone()
    conn.close()
    
    return dict(row) if row else None


def post_bto_signal(
    webhook_url: str,
    symbol: str,
    strike: float,
    expiry: str,
    call_put: str,
    qty: int,
    price: float,
    trade_type: str = 'Swing',
    bot_name: str = '',
    avatar_url: str = None
) -> Tuple[bool, str]:
    """Post a BTO (Buy to Open) signal to Discord webhook."""
    if not webhook_url:
        return False, "No webhook URL configured"
    
    position_id = open_webhook_position(symbol, strike, expiry, call_put, qty, price, trade_type, webhook_url)
    if not position_id:
        return False, "Failed to open position for tracking"
    
    option_display = format_option_display(symbol, strike, expiry, call_put)
    
    main_message = f"BTO {qty} {option_display} @ {price:.2f} @everyone ({trade_type})"
    
    embed = {
        "description": f"Opened {qty} {option_display} @ ${price:.2f} (Actual Cost: ${price:.2f})",
        "color": 3066993,
        "footer": {
            "text": datetime.now().strftime("%m/%d/%Y %I:%M %p")
        }
    }
    
    payload = {
        "content": main_message,
        "embeds": [embed]
    }
    
    if bot_name:
        payload["username"] = bot_name
    if avatar_url:
        payload["avatar_url"] = avatar_url
    
    try:
        response = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        if response.status_code in [200, 204]:
            return True, f"BTO signal posted successfully (Position ID: {position_id})"
        else:
            return False, f"Webhook error: {response.status_code} - {response.text}"
    except requests.exceptions.RequestException as e:
        return False, f"Request failed: {str(e)}"


def post_stc_signal(
    webhook_url: str,
    symbol: str,
    strike: float,
    expiry: str,
    call_put: str,
    qty: int,
    close_price: float,
    bot_name: str = '',
    avatar_url: str = None
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Post an STC (Sell to Close) signal to Discord webhook with P&L."""
    if not webhook_url:
        return False, "No webhook URL configured", None
    
    result = close_webhook_position(symbol, strike, expiry, call_put, qty, close_price, webhook_url=webhook_url)
    
    if not result:
        return False, f"No open position found for {symbol} {strike}{call_put} {expiry}", None
    
    option_display = format_option_display(symbol, strike, expiry, call_put)
    
    pnl_sign = "+" if result['pnl_percent'] >= 0 else ""
    pnl_color = 3066993 if result['pnl_percent'] >= 0 else 15158332
    
    main_text = f"STC {result['close_qty']} {option_display} @ {close_price:.2f} @everyone (Entry: ${result['entry_price']:.2f}) | Gain: {pnl_sign}{result['pnl_percent']:.1f}%"
    
    summary_embed = {
        "title": "Trade Summary",
        "color": pnl_color,
        "fields": [
            {
                "name": "Total Closed",
                "value": f"{result['total_closed']}/{result['original_qty']}",
                "inline": True
            },
            {
                "name": "Average Close Price",
                "value": f"${result['avg_close_price']:.2f}",
                "inline": True
            },
            {
                "name": "Total Profit",
                "value": f"${result['total_pnl']:+.2f}",
                "inline": True
            }
        ],
        "footer": {
            "text": datetime.now().strftime("%m/%d/%Y %I:%M %p")
        }
    }
    
    payload = {
        "content": main_text,
        "embeds": [summary_embed]
    }
    
    if bot_name:
        payload["username"] = bot_name
    if avatar_url:
        payload["avatar_url"] = avatar_url
    
    try:
        response = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        if response.status_code in [200, 204]:
            return True, f"STC signal posted successfully (P&L: {pnl_sign}{result['pnl_percent']:.1f}%)", result
        else:
            return False, f"Webhook error: {response.status_code} - {response.text}", result
    except requests.exceptions.RequestException as e:
        return False, f"Request failed: {str(e)}", result


def test_webhook(webhook_url: str, bot_name: str = '') -> Tuple[bool, str]:
    """Test a webhook URL by sending a test message."""
    if not webhook_url:
        return False, "No webhook URL provided"
    
    payload = {
        "content": "Webhook test successful! BotifyTrades webhook is connected."
    }
    if bot_name:
        payload["username"] = bot_name
    
    try:
        response = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        if response.status_code in [200, 204]:
            return True, "Webhook test successful!"
        else:
            return False, f"Webhook error: {response.status_code}"
    except requests.exceptions.RequestException as e:
        return False, f"Connection failed: {str(e)}"
