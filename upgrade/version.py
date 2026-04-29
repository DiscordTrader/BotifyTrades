"""
Version Management
==================
Handles semantic versioning for the application.

NOTE: This module does NOT require git. Version is hardcoded below.
Build scripts read APP_VERSION directly - no git tags or commands needed.
"""

import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict


APP_VERSION = "9.3.3"
BUILD_DATE = "2026-04-29"


def parse_version(version_str: str) -> Tuple[int, int, int]:
    """Parse a semantic version string into tuple of (major, minor, patch)."""
    if not version_str:
        return (0, 0, 0)
    
    version_str = version_str.lstrip('v').strip()
    
    match = re.match(r'^(\d+)\.(\d+)\.(\d+)', version_str)
    if match:
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    
    match = re.match(r'^(\d+)\.(\d+)', version_str)
    if match:
        return (int(match.group(1)), int(match.group(2)), 0)
    
    match = re.match(r'^(\d+)', version_str)
    if match:
        return (int(match.group(1)), 0, 0)
    
    return (0, 0, 0)


def compare_versions(v1: str, v2: str) -> int:
    """
    Compare two version strings.
    
    Returns:
        -1 if v1 < v2
         0 if v1 == v2
         1 if v1 > v2
    """
    t1 = parse_version(v1)
    t2 = parse_version(v2)
    
    if t1 < t2:
        return -1
    elif t1 > t2:
        return 1
    return 0


def get_db_path() -> str:
    """Get the database path, searching common locations."""
    import sys
    
    env_path = os.environ.get('DATABASE_PATH')
    if env_path and Path(env_path).exists():
        return env_path
    
    db_name = 'bot_data.db'
    possible_paths = [
        Path(db_name),
        Path(sys.executable).parent / db_name if getattr(sys, 'frozen', False) else None,
        Path.cwd() / db_name,
        Path(__file__).parent.parent / db_name,
    ]
    
    for path in possible_paths:
        if path and path.exists():
            return str(path)
    
    return db_name


def get_current_version() -> str:
    """Get the current installed version from database or return default."""
    try:
        db_path = get_db_path()
        if not Path(db_path).exists():
            return APP_VERSION
        
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='app_version'")
        if not cursor.fetchone():
            conn.close()
            return APP_VERSION
        
        cursor.execute("SELECT version FROM app_version ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        
        return row['version'] if row else APP_VERSION
        
    except Exception as e:
        print(f"[VERSION] Error getting version: {e}")
        return APP_VERSION


def set_current_version(version: str) -> bool:
    """Set the current version in the database."""
    try:
        db_path = get_db_path()
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_version (
                id INTEGER PRIMARY KEY,
                version TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        cursor.execute(
            "INSERT INTO app_version (version, updated_at) VALUES (?, ?)",
            (version, datetime.now().isoformat())
        )
        
        conn.commit()
        conn.close()
        return True
        
    except Exception as e:
        print(f"[VERSION] Error setting version: {e}")
        return False


def get_version_info() -> Dict:
    """Get comprehensive version information."""
    current = get_current_version()
    major, minor, patch = parse_version(current)
    
    return {
        'version': current,
        'major': major,
        'minor': minor,
        'patch': patch,
        'display': f"v{current}",
        'app_version': APP_VERSION,
        'build_date': BUILD_DATE
    }



