"""
Migration Manager Module
========================
Handles database migrations with versioning and rollback capability.
"""

import os
import sqlite3
import json
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .validator import find_database_path

MIGRATIONS_DIR = Path(__file__).parent / 'migrations' / 'versions'


@dataclass
class Migration:
    """Represents a database migration"""
    version: str
    name: str
    description: str
    up_sql: str
    down_sql: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    applied_at: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            'version': self.version,
            'name': self.name,
            'description': self.description,
            'created_at': self.created_at,
            'applied_at': self.applied_at
        }


class MigrationManager:
    """
    Manages database migrations with:
    - Version tracking
    - Up/down migrations
    - Rollback capability
    - Pre/post validation
    """
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or find_database_path() or 'gui_app/trading_bot.db'
        self._conn = None
        self._db_available = os.path.exists(self.db_path)
        if self._db_available:
            self._ensure_migration_table()
    
    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn
    
    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
    
    def _ensure_migration_table(self):
        """Create migrations tracking table if not exists"""
        conn = self._get_connection()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS _qa_migrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                applied_at TEXT DEFAULT CURRENT_TIMESTAMP,
                rolled_back_at TEXT
            )
        ''')
        conn.commit()
    
    def get_current_version(self) -> Optional[str]:
        """Get the current database version"""
        conn = self._get_connection()
        cursor = conn.execute('''
            SELECT version FROM _qa_migrations 
            WHERE rolled_back_at IS NULL 
            ORDER BY applied_at DESC LIMIT 1
        ''')
        row = cursor.fetchone()
        return row['version'] if row else None
    
    def get_applied_migrations(self) -> List[Dict]:
        """Get list of applied migrations"""
        conn = self._get_connection()
        cursor = conn.execute('''
            SELECT version, name, description, applied_at 
            FROM _qa_migrations 
            WHERE rolled_back_at IS NULL
            ORDER BY applied_at ASC
        ''')
        return [dict(row) for row in cursor.fetchall()]
    
    def create_migration(
        self,
        name: str,
        description: str,
        up_sql: str,
        down_sql: str
    ) -> Migration:
        """Create a new migration file"""
        # Generate version based on timestamp
        version = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        migration = Migration(
            version=version,
            name=name,
            description=description,
            up_sql=up_sql,
            down_sql=down_sql
        )
        
        # Save to file
        MIGRATIONS_DIR.mkdir(parents=True, exist_ok=True)
        filepath = MIGRATIONS_DIR / f"{version}_{name}.json"
        
        with open(filepath, 'w') as f:
            json.dump({
                'version': version,
                'name': name,
                'description': description,
                'up_sql': up_sql,
                'down_sql': down_sql,
                'created_at': migration.created_at
            }, f, indent=2)
        
        return migration
    
    def apply_migration(self, migration: Migration) -> Tuple[bool, str]:
        """Apply a migration"""
        conn = self._get_connection()
        
        try:
            # Execute up SQL
            conn.executescript(migration.up_sql)
            
            # Record migration
            conn.execute('''
                INSERT INTO _qa_migrations (version, name, description)
                VALUES (?, ?, ?)
            ''', (migration.version, migration.name, migration.description))
            
            conn.commit()
            return True, f"Migration {migration.version} applied successfully"
            
        except Exception as e:
            conn.rollback()
            return False, f"Migration failed: {str(e)}"
    
    def rollback_migration(self, version: str) -> Tuple[bool, str]:
        """Rollback a specific migration"""
        # Load migration file
        migration_file = None
        for f in MIGRATIONS_DIR.glob(f"{version}_*.json"):
            migration_file = f
            break
        
        if not migration_file:
            return False, f"Migration file for version {version} not found"
        
        with open(migration_file, 'r') as f:
            migration_data = json.load(f)
        
        conn = self._get_connection()
        
        try:
            # Execute down SQL
            conn.executescript(migration_data['down_sql'])
            
            # Mark as rolled back
            conn.execute('''
                UPDATE _qa_migrations 
                SET rolled_back_at = CURRENT_TIMESTAMP
                WHERE version = ?
            ''', (version,))
            
            conn.commit()
            return True, f"Migration {version} rolled back successfully"
            
        except Exception as e:
            conn.rollback()
            return False, f"Rollback failed: {str(e)}"
    
    def validate_migration(self, migration: Migration) -> Tuple[bool, List[str]]:
        """Validate a migration before applying"""
        issues = []
        
        # Check up_sql is valid
        if not migration.up_sql or not migration.up_sql.strip():
            issues.append("Migration up_sql is empty")
        
        # Check down_sql is valid
        if not migration.down_sql or not migration.down_sql.strip():
            issues.append("Migration down_sql is empty (no rollback possible)")
        
        # Check version format
        if not migration.version or len(migration.version) < 8:
            issues.append("Invalid version format")
        
        # Check for destructive operations without confirmation
        destructive_keywords = ['DROP TABLE', 'DELETE FROM', 'TRUNCATE']
        for keyword in destructive_keywords:
            if keyword in migration.up_sql.upper():
                issues.append(f"Destructive operation detected: {keyword}")
        
        return len(issues) == 0, issues
    
    def get_pending_migrations(self) -> List[Migration]:
        """Get migrations that haven't been applied yet"""
        applied_versions = {m['version'] for m in self.get_applied_migrations()}
        pending = []
        
        for migration_file in sorted(MIGRATIONS_DIR.glob('*.json')):
            with open(migration_file, 'r') as f:
                data = json.load(f)
            
            if data['version'] not in applied_versions:
                pending.append(Migration(
                    version=data['version'],
                    name=data['name'],
                    description=data.get('description', ''),
                    up_sql=data['up_sql'],
                    down_sql=data['down_sql'],
                    created_at=data.get('created_at', '')
                ))
        
        return pending
    
    def apply_pending(self) -> Dict[str, Any]:
        """Apply all pending migrations"""
        pending = self.get_pending_migrations()
        results = {
            'applied': [],
            'failed': [],
            'total': len(pending)
        }
        
        for migration in pending:
            # Validate first
            valid, issues = self.validate_migration(migration)
            if not valid:
                results['failed'].append({
                    'version': migration.version,
                    'reason': issues
                })
                continue
            
            # Apply
            success, message = self.apply_migration(migration)
            if success:
                results['applied'].append(migration.version)
            else:
                results['failed'].append({
                    'version': migration.version,
                    'reason': message
                })
                break  # Stop on first failure
        
        return results


# =========================================
# Helper functions for common migrations
# =========================================

def create_add_column_migration(
    table: str,
    column: str,
    column_type: str,
    default: str = None,
    description: str = None
) -> Dict[str, str]:
    """
    Generate SQL for adding a column.
    
    Usage:
        migration = create_add_column_migration(
            table='channels',
            column='new_feature_enabled',
            column_type='INTEGER',
            default='0'
        )
    """
    default_clause = f" DEFAULT {default}" if default else ""
    
    up_sql = f"ALTER TABLE {table} ADD COLUMN {column} {column_type}{default_clause};"
    
    # SQLite doesn't support DROP COLUMN directly, so down_sql is a comment
    down_sql = f"-- SQLite: Cannot drop column. To rollback, recreate table without {column}"
    
    return {
        'name': f'add_{column}_to_{table}',
        'description': description or f'Add {column} column to {table} table',
        'up_sql': up_sql,
        'down_sql': down_sql
    }


def generate_migration_template(name: str) -> str:
    """Generate a migration template file content"""
    version = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    return f'''{{
  "version": "{version}",
  "name": "{name}",
  "description": "TODO: Add description",
  "up_sql": "-- TODO: Add migration SQL",
  "down_sql": "-- TODO: Add rollback SQL",
  "created_at": "{datetime.now().isoformat()}"
}}
'''
