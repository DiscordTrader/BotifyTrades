#!/usr/bin/env python3
"""
Database Migration System
=========================
Manages database schema migrations with version tracking and rollback support.
"""
import os
import json
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple


MIGRATIONS_DIR = Path('migrations')
BACKUP_DIR = Path('migrations/backups')


def get_db_path() -> str:
    """Get the primary database path."""
    return os.environ.get('DATABASE_PATH', 'bot_data.db')


class Migration:
    """Represents a database migration."""
    
    def __init__(self, version: str, name: str, up_sql: str, down_sql: str = None):
        self.version = version
        self.name = name
        self.up_sql = up_sql
        self.down_sql = down_sql or ""
        self.applied_at: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            'version': self.version,
            'name': self.name,
            'up_sql': self.up_sql,
            'down_sql': self.down_sql,
            'applied_at': self.applied_at
        }


class MigrationManager:
    """Manages database migrations."""
    
    # Schema definition for required tables
    SCHEMA_DEFINITIONS = {
        'app_version': """
            CREATE TABLE IF NOT EXISTS app_version (
                id INTEGER PRIMARY KEY,
                version TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """,
        'applied_migrations': """
            CREATE TABLE IF NOT EXISTS applied_migrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL,
                rollback_sql TEXT
            )
        """,
        'server_licenses': """
            CREATE TABLE IF NOT EXISTS server_licenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                license_key TEXT UNIQUE NOT NULL,
                customer_name TEXT NOT NULL,
                customer_email TEXT,
                license_type TEXT DEFAULT 'standard',
                status TEXT DEFAULT 'active',
                max_devices INTEGER DEFAULT 3,
                active_devices TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                expires_at TEXT,
                last_validated TEXT,
                notes TEXT
            )
        """,
        'settings': """
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT,
                updated_at TEXT
            )
        """,
        'channels': """
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT UNIQUE NOT NULL,
                channel_name TEXT,
                guild_id TEXT,
                guild_name TEXT,
                is_enabled INTEGER DEFAULT 1,
                execute_enabled INTEGER DEFAULT 0,
                track_enabled INTEGER DEFAULT 1,
                broker_override TEXT,
                allowed_users TEXT DEFAULT '[]',
                risk_settings TEXT DEFAULT '{}',
                created_at TEXT,
                updated_at TEXT
            )
        """,
        'trades': """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                entry_price REAL,
                exit_price REAL,
                status TEXT DEFAULT 'open',
                broker TEXT,
                source_channel_id TEXT,
                source_channel_name TEXT,
                source_author_id TEXT,
                stop_loss REAL,
                profit_target REAL,
                trailing_stop_pct REAL,
                pnl REAL,
                pnl_pct REAL,
                created_at TEXT,
                closed_at TEXT,
                exit_type TEXT,
                notes TEXT
            )
        """,
        'signals': """
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                channel_id TEXT,
                channel_name TEXT,
                author TEXT,
                message_content TEXT,
                signal_type TEXT,
                symbol TEXT,
                quantity REAL,
                price REAL,
                option_type TEXT,
                strike REAL,
                expiry TEXT,
                executed INTEGER DEFAULT 0,
                trade_id INTEGER,
                FOREIGN KEY (trade_id) REFERENCES trades(id)
            )
        """,
        'patch_history': """
            CREATE TABLE IF NOT EXISTS patch_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_version TEXT,
                to_version TEXT NOT NULL,
                patch_type TEXT DEFAULT 'minor',
                status TEXT DEFAULT 'pending',
                started_at TEXT,
                completed_at TEXT,
                backup_path TEXT,
                changelog TEXT,
                error_message TEXT,
                notes TEXT
            )
        """
    }
    
    # Indices for performance
    INDICES = [
        "CREATE INDEX IF NOT EXISTS idx_channels_channel_id ON channels(channel_id)",
        "CREATE INDEX IF NOT EXISTS idx_trades_source_channel ON trades(source_channel_id)",
        "CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)",
        "CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)",
        "CREATE INDEX IF NOT EXISTS idx_signals_channel_id ON signals(channel_id)",
        "CREATE INDEX IF NOT EXISTS idx_server_licenses_key ON server_licenses(license_key)",
        "CREATE INDEX IF NOT EXISTS idx_server_licenses_status ON server_licenses(status)",
        "CREATE INDEX IF NOT EXISTS idx_patch_history_version ON patch_history(to_version)",
        "CREATE INDEX IF NOT EXISTS idx_patch_history_status ON patch_history(status)",
    ]
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or get_db_path()
        MIGRATIONS_DIR.mkdir(exist_ok=True)
        BACKUP_DIR.mkdir(exist_ok=True)
    
    def get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def ensure_migration_tables(self):
        """Ensure migration tracking tables exist."""
        conn = self.get_connection()
        conn.execute(self.SCHEMA_DEFINITIONS['app_version'])
        conn.execute(self.SCHEMA_DEFINITIONS['applied_migrations'])
        conn.commit()
        conn.close()
    
    def get_current_version(self) -> Optional[str]:
        """Get current application version."""
        try:
            conn = self.get_connection()
            row = conn.execute("SELECT version FROM app_version ORDER BY id DESC LIMIT 1").fetchone()
            conn.close()
            return row['version'] if row else None
        except:
            return None
    
    def set_version(self, version: str):
        """Set application version."""
        self.ensure_migration_tables()
        conn = self.get_connection()
        conn.execute(
            "INSERT INTO app_version (version, updated_at) VALUES (?, ?)",
            (version, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
    
    def get_applied_migrations(self) -> List[str]:
        """Get list of applied migration versions."""
        try:
            conn = self.get_connection()
            rows = conn.execute("SELECT version FROM applied_migrations ORDER BY id").fetchall()
            conn.close()
            return [row['version'] for row in rows]
        except:
            return []
    
    def backup_database(self) -> str:
        """Create a backup of the database."""
        if not Path(self.db_path).exists():
            return None
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = BACKUP_DIR / f"backup_{timestamp}.db"
        shutil.copy2(self.db_path, backup_path)
        
        print(f"[MIGRATION] Backup created: {backup_path}")
        return str(backup_path)
    
    def restore_backup(self, backup_path: str) -> bool:
        """Restore database from backup."""
        try:
            shutil.copy2(backup_path, self.db_path)
            print(f"[MIGRATION] Database restored from: {backup_path}")
            return True
        except Exception as e:
            print(f"[MIGRATION] Restore failed: {e}")
            return False
    
    def apply_schema(self, table_name: str) -> Tuple[bool, str]:
        """Apply schema for a specific table."""
        if table_name not in self.SCHEMA_DEFINITIONS:
            return False, f"Unknown table: {table_name}"
        
        try:
            conn = self.get_connection()
            conn.execute(self.SCHEMA_DEFINITIONS[table_name])
            conn.commit()
            conn.close()
            return True, f"Table '{table_name}' created/verified"
        except Exception as e:
            return False, str(e)
    
    def apply_all_schemas(self) -> Dict[str, Tuple[bool, str]]:
        """Apply all schema definitions."""
        results = {}
        
        self.ensure_migration_tables()
        self.backup_database()
        
        for table_name in self.SCHEMA_DEFINITIONS:
            results[table_name] = self.apply_schema(table_name)
        
        # Apply indices
        conn = self.get_connection()
        for idx_sql in self.INDICES:
            try:
                conn.execute(idx_sql)
            except Exception as e:
                print(f"[MIGRATION] Index warning: {e}")
        conn.commit()
        conn.close()
        
        return results
    
    def record_migration(self, version: str, name: str, rollback_sql: str = None):
        """Record a migration as applied."""
        self.ensure_migration_tables()
        conn = self.get_connection()
        conn.execute(
            "INSERT INTO applied_migrations (version, name, applied_at, rollback_sql) VALUES (?, ?, ?, ?)",
            (version, name, datetime.now().isoformat(), rollback_sql)
        )
        conn.commit()
        conn.close()
    
    def validate_schema(self) -> Dict[str, bool]:
        """Validate that all required tables exist."""
        results = {}
        
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            existing = {row[0] for row in cursor.fetchall()}
            conn.close()
            
            for table_name in self.SCHEMA_DEFINITIONS:
                results[table_name] = table_name in existing
        except Exception as e:
            print(f"[MIGRATION] Validation error: {e}")
        
        return results
    
    def get_missing_tables(self) -> List[str]:
        """Get list of missing required tables."""
        validation = self.validate_schema()
        return [table for table, exists in validation.items() if not exists]
    
    def upgrade(self) -> Dict:
        """Run upgrade to ensure all tables exist."""
        print("[MIGRATION] Starting upgrade...")
        
        missing = self.get_missing_tables()
        if not missing:
            print("[MIGRATION] All tables present, nothing to upgrade")
            return {'status': 'current', 'tables_created': []}
        
        print(f"[MIGRATION] Missing tables: {missing}")
        
        # Backup before changes
        backup = self.backup_database()
        
        # Apply missing schemas
        created = []
        for table in missing:
            success, msg = self.apply_schema(table)
            if success:
                created.append(table)
                print(f"[MIGRATION] Created: {table}")
            else:
                print(f"[MIGRATION] Failed: {table} - {msg}")
        
        # Apply indices
        conn = self.get_connection()
        for idx_sql in self.INDICES:
            try:
                conn.execute(idx_sql)
            except:
                pass
        conn.commit()
        conn.close()
        
        # Record migration
        version = datetime.now().strftime('%Y%m%d%H%M%S')
        self.record_migration(version, f"Created tables: {', '.join(created)}")
        
        return {
            'status': 'upgraded',
            'tables_created': created,
            'backup': backup,
            'version': version
        }


def run_upgrade():
    """Run database upgrade."""
    manager = MigrationManager()
    return manager.upgrade()


def validate_schema():
    """Validate database schema."""
    manager = MigrationManager()
    return manager.validate_schema()


def get_missing_tables():
    """Get missing tables."""
    manager = MigrationManager()
    return manager.get_missing_tables()


if __name__ == '__main__':
    import sys
    
    manager = MigrationManager()
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == 'upgrade':
            result = manager.upgrade()
            print(f"\nUpgrade result: {result}")
        elif command == 'validate':
            result = manager.validate_schema()
            print("\nSchema validation:")
            for table, exists in result.items():
                status = '✓' if exists else '✗'
                print(f"  {status} {table}")
        elif command == 'backup':
            path = manager.backup_database()
            print(f"\nBackup created: {path}")
        else:
            print(f"Unknown command: {command}")
            print("Usage: python migrations.py [upgrade|validate|backup]")
    else:
        # Default: show status
        print("Database Migration Manager")
        print("=" * 40)
        
        version = manager.get_current_version()
        print(f"Current version: {version or 'Not set'}")
        
        missing = manager.get_missing_tables()
        if missing:
            print(f"Missing tables: {', '.join(missing)}")
            print("\nRun 'python migrations.py upgrade' to create missing tables")
        else:
            print("All tables present ✓")
