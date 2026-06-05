#!/usr/bin/env python3
"""
Database Schema Validation Script
==================================
Validates that all required database tables and columns exist.
"""
import sqlite3
import sys
from pathlib import Path

REQUIRED_TABLES = {
    'settings': ['key', 'value'],
    'channels': ['discord_channel_id', 'name', 'category', 'execute_enabled', 'track_enabled', 'broker_override'],
    'trades': ['symbol', 'direction', 'quantity', 'intended_price', 'broker', 'status', 'channel_id'],
    'server_licenses': ['license_key', 'customer_name', 'license_type', 'status', 'expires_at'],
}

def validate_schema(db_path: str) -> bool:
    """Validate database schema has all required tables and columns."""
    if not Path(db_path).exists():
        print(f"  ⚠️  Database not found: {db_path}")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing_tables = {row[0] for row in cursor.fetchall()}
    
    all_valid = True
    
    for table, required_columns in REQUIRED_TABLES.items():
        if table not in existing_tables:
            print(f"  ❌ Missing table: {table}")
            all_valid = False
            continue
        
        cursor.execute(f"PRAGMA table_info({table})")
        existing_columns = {row[1] for row in cursor.fetchall()}
        
        missing_columns = set(required_columns) - existing_columns
        if missing_columns:
            print(f"  ❌ Table '{table}' missing columns: {missing_columns}")
            all_valid = False
        else:
            print(f"  ✓ Table '{table}' has all required columns")
    
    conn.close()
    return all_valid

def main():
    """Main validation function."""
    print("Database Schema Validation")
    print("-" * 40)
    
    db_paths = [
        'bot_data.db',
        'license_server.db',
    ]
    
    found_db = False
    for db_path in db_paths:
        if Path(db_path).exists():
            found_db = True
            print(f"\nChecking: {db_path}")
            if validate_schema(db_path):
                print(f"  ✓ Schema valid: {db_path}")
            else:
                print(f"  ⚠️  Schema issues found in: {db_path}")
    
    if not found_db:
        print("  ⚠️  No database files found (will be created on first run)")
    
    print("\nSchema validation complete.")
    return 0

if __name__ == '__main__':
    sys.exit(main())
