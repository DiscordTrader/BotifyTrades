"""
Backup Manager
==============
Handles database backup and restore operations for safe upgrades.
"""

import os
import shutil
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple


BACKUP_DIR = Path('upgrade/backups')


class BackupManager:
    """Manages database backups for safe upgrades."""
    
    def __init__(self, db_path: str = None, backup_dir: Path = None, retention_count: int = 5):
        self.db_path = db_path or os.environ.get('DATABASE_PATH') or self._find_database()
        self.backup_dir = backup_dir or BACKUP_DIR
        self.retention_count = retention_count
        self.backup_dir.mkdir(parents=True, exist_ok=True)
    
    def _find_database(self) -> str:
        """Find the database file in common locations."""
        import sys
        
        possible_paths = [
            'bot_data.db',
            Path(sys.executable).parent / 'bot_data.db' if getattr(sys, 'frozen', False) else None,
            Path.cwd() / 'bot_data.db',
            Path(__file__).parent.parent / 'bot_data.db',
        ]
        
        for path in possible_paths:
            if path and Path(path).exists():
                print(f"[BACKUP] Found database at: {path}")
                return str(path)
        
        return 'bot_data.db'
    
    def create_backup(self, tag: str = None) -> Tuple[bool, str, str]:
        """
        Create a backup of the database.
        
        Args:
            tag: Optional tag for the backup (e.g., 'pre-upgrade', 'manual')
            
        Returns:
            Tuple of (success, backup_path, error_message)
        """
        if not Path(self.db_path).exists():
            return False, "", "Database file does not exist"
        
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            tag_part = f"_{tag}" if tag else ""
            backup_name = f"backup{tag_part}_{timestamp}.db"
            backup_path = self.backup_dir / backup_name
            
            source_conn = sqlite3.connect(self.db_path)
            dest_conn = sqlite3.connect(str(backup_path))
            source_conn.backup(dest_conn)
            source_conn.close()
            dest_conn.close()
            
            self._create_backup_metadata(backup_path, tag)
            
            self._cleanup_old_backups()
            
            print(f"[BACKUP] Created: {backup_path}")
            return True, str(backup_path), ""
            
        except Exception as e:
            error_msg = f"Backup failed: {str(e)}"
            print(f"[BACKUP] {error_msg}")
            return False, "", error_msg
    
    def _create_backup_metadata(self, backup_path: Path, tag: str = None):
        """Create metadata file for the backup."""
        try:
            from .version import get_current_version
            version = get_current_version()
        except:
            version = "unknown"
        
        metadata = {
            'created_at': datetime.now().isoformat(),
            'db_path': self.db_path,
            'backup_path': str(backup_path),
            'tag': tag,
            'version': version,
            'size_bytes': backup_path.stat().st_size if backup_path.exists() else 0
        }
        
        metadata_path = backup_path.with_suffix('.json')
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
    
    def restore_backup(self, backup_path: str) -> Tuple[bool, str]:
        """
        Restore database from a backup.
        
        Args:
            backup_path: Path to the backup file
            
        Returns:
            Tuple of (success, error_message)
        """
        backup_file = Path(backup_path)
        if not backup_file.exists():
            return False, f"Backup file not found: {backup_path}"
        
        try:
            self.create_backup(tag='pre-restore')
            
            source_conn = sqlite3.connect(str(backup_file))
            dest_conn = sqlite3.connect(self.db_path)
            source_conn.backup(dest_conn)
            source_conn.close()
            dest_conn.close()
            
            print(f"[BACKUP] Restored from: {backup_path}")
            return True, ""
            
        except Exception as e:
            error_msg = f"Restore failed: {str(e)}"
            print(f"[BACKUP] {error_msg}")
            return False, error_msg
    
    def list_backups(self) -> List[Dict]:
        """List all available backups with metadata."""
        backups = []
        
        for backup_file in sorted(self.backup_dir.glob('backup_*.db'), reverse=True):
            metadata_path = backup_file.with_suffix('.json')
            
            if metadata_path.exists():
                try:
                    with open(metadata_path, 'r') as f:
                        metadata = json.load(f)
                except:
                    metadata = {}
            else:
                metadata = {}
            
            backups.append({
                'path': str(backup_file),
                'filename': backup_file.name,
                'created_at': metadata.get('created_at', backup_file.stat().st_mtime),
                'tag': metadata.get('tag'),
                'version': metadata.get('version'),
                'size_bytes': metadata.get('size_bytes', backup_file.stat().st_size),
                'size_display': self._format_size(backup_file.stat().st_size)
            })
        
        return backups
    
    def get_latest_backup(self, tag: str = None) -> Optional[Dict]:
        """Get the most recent backup, optionally filtered by tag."""
        backups = self.list_backups()
        
        if tag:
            backups = [b for b in backups if b.get('tag') == tag]
        
        return backups[0] if backups else None
    
    def _cleanup_old_backups(self):
        """Remove old backups beyond retention count."""
        backups = sorted(self.backup_dir.glob('backup_*.db'), reverse=True)
        
        for old_backup in backups[self.retention_count:]:
            try:
                old_backup.unlink()
                metadata_path = old_backup.with_suffix('.json')
                if metadata_path.exists():
                    metadata_path.unlink()
                print(f"[BACKUP] Removed old backup: {old_backup.name}")
            except Exception as e:
                print(f"[BACKUP] Failed to remove {old_backup.name}: {e}")
    
    def verify_backup(self, backup_path: str) -> Tuple[bool, str]:
        """
        Verify a backup file is valid and can be restored.
        
        Returns:
            Tuple of (is_valid, message)
        """
        backup_file = Path(backup_path)
        if not backup_file.exists():
            return False, "Backup file not found"
        
        try:
            conn = sqlite3.connect(str(backup_file))
            cursor = conn.cursor()
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            conn.close()
            
            if not tables:
                return False, "Backup contains no tables"
            
            return True, f"Valid backup with {len(tables)} tables"
            
        except Exception as e:
            return False, f"Invalid backup: {str(e)}"
    
    def get_disk_space(self) -> Dict:
        """Get disk space information for backup directory."""
        try:
            import shutil
            total, used, free = shutil.disk_usage(self.backup_dir)
            return {
                'total_bytes': total,
                'used_bytes': used,
                'free_bytes': free,
                'total_display': self._format_size(total),
                'free_display': self._format_size(free),
                'backup_dir_size': self._get_directory_size(self.backup_dir),
                'backup_count': len(list(self.backup_dir.glob('backup_*.db')))
            }
        except Exception as e:
            return {'error': str(e)}
    
    def _get_directory_size(self, path: Path) -> int:
        """Get total size of a directory."""
        total = 0
        for file in path.glob('**/*'):
            if file.is_file():
                total += file.stat().st_size
        return total
    
    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format bytes as human-readable size."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"


_backup_manager: Optional[BackupManager] = None


def get_backup_manager() -> BackupManager:
    """Get or create the global backup manager instance."""
    global _backup_manager
    if _backup_manager is None:
        _backup_manager = BackupManager()
    return _backup_manager


def create_backup(tag: str = None) -> Tuple[bool, str, str]:
    """Convenience function to create a backup."""
    return get_backup_manager().create_backup(tag)


def restore_backup(backup_path: str) -> Tuple[bool, str]:
    """Convenience function to restore from backup."""
    return get_backup_manager().restore_backup(backup_path)


def list_backups() -> List[Dict]:
    """Convenience function to list backups."""
    return get_backup_manager().list_backups()
