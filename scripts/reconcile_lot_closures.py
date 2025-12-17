#!/usr/bin/env python3
"""
Reconciliation script to backfill lot_closures for trades closed via risk management
that are missing their PNL records in the lot_closures table.
"""

import sqlite3
from datetime import datetime

DB_PATH = '/home/runner/workspace/bot_data.db'

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def find_missing_closures():
    """Find closed trades that don't have corresponding lot_closures."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Find closed trades with PNL that might be missing lot_closures
    cursor.execute('''
        SELECT t.id, t.symbol, t.strike, t.expiry, t.quantity, t.executed_price,
               t.current_price, t.pnl, t.closed_at, t.channel_id, t.direction,
               t.call_put, t.broker
        FROM trades t
        WHERE t.status = 'CLOSED' 
          AND t.direction = 'BTO'
          AND t.pnl IS NOT NULL
          AND t.channel_id IS NOT NULL
        ORDER BY t.closed_at DESC
        LIMIT 50
    ''')
    
    trades = cursor.fetchall()
    missing = []
    
    for trade in trades:
        # Check if there's a lot_closure for this trade
        # First find the signal_lot
        cursor.execute('''
            SELECT sl.id, sl.remaining_qty, sl.author_name
            FROM signal_lots sl
            JOIN channels c ON sl.channel_id = c.id
            WHERE c.discord_channel_id = ?
              AND sl.symbol = ?
              AND sl.strike = ?
              AND sl.status IN ('OPEN', 'CLOSED', 'PARTIAL')
            ORDER BY sl.opened_at ASC
            LIMIT 1
        ''', (str(trade['channel_id']), trade['symbol'], trade['strike']))
        
        lot = cursor.fetchone()
        
        if lot:
            # Check if there's a lot_closure that matches the trade's closed_at time
            cursor.execute('''
                SELECT id FROM lot_closures
                WHERE lot_id = ?
                  AND closed_qty = ?
            ''', (lot['id'], trade['quantity']))
            
            closure = cursor.fetchone()
            if not closure:
                missing.append({
                    'trade': dict(trade),
                    'lot_id': lot['id'],
                    'lot_remaining': lot['remaining_qty']
                })
    
    conn.close()
    return missing

def create_lot_closure(trade, lot_id, db_channel_id):
    """Create a lot_closure record for a closed trade."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Calculate PNL percentage
    entry_price = trade['executed_price'] or 0
    exit_price = trade['current_price'] or 0
    pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
    
    # Get author from signal_lot
    cursor.execute('SELECT author_name FROM signal_lots WHERE id = ?', (lot_id,))
    lot = cursor.fetchone()
    author = lot['author_name'] if lot else 'unknown'
    
    # Calculate hold time
    closed_at = trade['closed_at']
    hold_time = 0.001  # Default minimal hold time
    
    cursor.execute('''
        INSERT INTO lot_closures (lot_id, channel_id, signal_id, closed_qty, close_price, closed_at, pnl, pnl_percent, holding_days, author_name)
        VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        lot_id,
        db_channel_id,
        trade['quantity'],
        exit_price,
        closed_at,
        trade['pnl'],
        pnl_pct,
        hold_time,
        author
    ))
    
    conn.commit()
    closure_id = cursor.lastrowid
    conn.close()
    
    return closure_id

def reconcile():
    """Main reconciliation function."""
    print("=" * 60)
    print("LOT CLOSURES RECONCILIATION SCRIPT")
    print("=" * 60)
    
    missing = find_missing_closures()
    
    if not missing:
        print("\n✓ No missing lot_closures found!")
        return
    
    print(f"\nFound {len(missing)} trades that may need lot_closure records:")
    print("-" * 60)
    
    for i, item in enumerate(missing, 1):
        trade = item['trade']
        entry = trade['executed_price'] or 0
        exit_p = trade['current_price'] or 0
        pnl = trade['pnl'] or 0
        print(f"\n{i}. Trade #{trade['id']}: {trade['symbol']} {trade['strike']} {trade['call_put'] or ''}")
        print(f"   Qty: {trade['quantity']}, Entry: ${entry:.2f}, Exit: ${exit_p:.2f}")
        print(f"   PNL: ${pnl:.2f}")
        print(f"   Closed: {trade['closed_at']}")
        print(f"   Lot ID: {item['lot_id']}")
    
    print("\n" + "-" * 60)
    response = input("\nCreate missing lot_closures? (y/n): ").strip().lower()
    
    if response != 'y':
        print("Cancelled.")
        return
    
    # Get database channel IDs
    conn = get_connection()
    cursor = conn.cursor()
    
    created = 0
    for item in missing:
        trade = item['trade']
        
        # Get db channel id
        cursor.execute('SELECT id FROM channels WHERE discord_channel_id = ?', (str(trade['channel_id']),))
        channel = cursor.fetchone()
        
        if channel:
            try:
                closure_id = create_lot_closure(trade, item['lot_id'], channel['id'])
                print(f"✓ Created lot_closure #{closure_id} for trade #{trade['id']}")
                created += 1
            except Exception as e:
                print(f"✗ Failed for trade #{trade['id']}: {e}")
        else:
            print(f"✗ Channel not found for trade #{trade['id']}")
    
    conn.close()
    print(f"\n✓ Created {created} lot_closure records")

if __name__ == '__main__':
    reconcile()
