"""
License Server Database - Manages license_server.db ONLY

This database module handles:
- License creation, validation, revocation
- Device binding and activation tracking
- Admin authentication

NO trading functionality - that belongs in the User Bot Build.
"""

import sqlite3
import os
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from contextlib import contextmanager

LICENSE_DB_PATH = 'license_server.db'


@contextmanager
def get_connection():
    """Context manager for database connections"""
    conn = sqlite3.connect(LICENSE_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_database():
    """Initialize the license server database"""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS licenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                license_key TEXT UNIQUE NOT NULL,
                license_type TEXT DEFAULT 'standard',
                customer_email TEXT,
                customer_name TEXT,
                max_devices INTEGER DEFAULT 1,
                expires_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                revoked INTEGER DEFAULT 0,
                revoked_at TEXT,
                revoked_reason TEXT,
                notes TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS device_activations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                license_key TEXT NOT NULL,
                device_id TEXT NOT NULL,
                device_name TEXT,
                activated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_seen TEXT,
                ip_address TEXT,
                FOREIGN KEY (license_key) REFERENCES licenses(license_key),
                UNIQUE(license_key, device_id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                email TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_login TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                license_key TEXT,
                admin_user TEXT,
                details TEXT,
                ip_address TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        print("[LICENSE_DB] ✓ License database initialized")


def hash_password(password: str) -> str:
    """Hash password with salt"""
    salt = secrets.token_hex(16)
    hash_val = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}${hash_val}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored hash"""
    try:
        salt, hash_val = stored_hash.split('$')
        return hashlib.sha256((salt + password).encode()).hexdigest() == hash_val
    except:
        return False


def create_admin(username: str, password: str, email: str = None) -> bool:
    """Create admin user"""
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO admin_users (username, password_hash, email)
                VALUES (?, ?, ?)
            ''', (username, hash_password(password), email))
            return True
        except sqlite3.IntegrityError:
            return False


def verify_admin(username: str, password: str) -> Optional[Dict]:
    """Verify admin credentials"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM admin_users WHERE username = ?', (username,))
        row = cursor.fetchone()
        if row and verify_password(password, row['password_hash']):
            cursor.execute(
                'UPDATE admin_users SET last_login = ? WHERE id = ?',
                (datetime.now().isoformat(), row['id'])
            )
            return dict(row)
    return None


def generate_license_key() -> str:
    """Generate a unique license key"""
    import uuid
    key = str(uuid.uuid4()).upper().replace('-', '')
    return f"BT-{key[:4]}-{key[4:8]}-{key[8:12]}-{key[12:16]}"


def create_license(
    license_type: str = 'standard',
    customer_email: str = None,
    customer_name: str = None,
    max_devices: int = 1,
    duration_days: int = 365,
    notes: str = None,
    license_key: str = None
) -> Dict:
    """Create a new license"""
    if not license_key:
        license_key = generate_license_key()
    
    expires_at = (datetime.now() + timedelta(days=duration_days)).isoformat()
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO licenses (license_key, license_type, customer_email, 
                                  customer_name, max_devices, expires_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (license_key, license_type, customer_email, customer_name,
              max_devices, expires_at, notes))
        
        return {
            'license_key': license_key,
            'license_type': license_type,
            'customer_email': customer_email,
            'customer_name': customer_name,
            'max_devices': max_devices,
            'expires_at': expires_at,
            'created_at': datetime.now().isoformat()
        }


def get_license(license_key: str) -> Optional[Dict]:
    """Get license by key"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM licenses WHERE license_key = ?', (license_key,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_all_licenses(
    page: int = 1,
    per_page: int = 50,
    status: str = None,
    search: str = None,
    sort_by: str = 'created_at',
    sort_order: str = 'desc'
) -> Dict:
    """Get all licenses with pagination and filtering"""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        where_clauses = []
        params = []
        
        if status == 'active':
            where_clauses.append("revoked = 0 AND (expires_at IS NULL OR expires_at > datetime('now'))")
        elif status == 'expired':
            where_clauses.append("revoked = 0 AND expires_at <= datetime('now')")
        elif status == 'revoked':
            where_clauses.append("revoked = 1")
        
        if search:
            where_clauses.append("(license_key LIKE ? OR customer_email LIKE ? OR customer_name LIKE ?)")
            search_param = f"%{search}%"
            params.extend([search_param, search_param, search_param])
        
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        
        valid_sorts = ['created_at', 'expires_at', 'customer_email', 'license_type']
        if sort_by not in valid_sorts:
            sort_by = 'created_at'
        sort_order = 'DESC' if sort_order.lower() == 'desc' else 'ASC'
        
        cursor.execute(f'SELECT COUNT(*) FROM licenses WHERE {where_sql}', params)
        total = cursor.fetchone()[0]
        
        offset = (page - 1) * per_page
        cursor.execute(f'''
            SELECT * FROM licenses 
            WHERE {where_sql}
            ORDER BY {sort_by} {sort_order}
            LIMIT ? OFFSET ?
        ''', params + [per_page, offset])
        
        licenses = [dict(row) for row in cursor.fetchall()]
        
        for lic in licenses:
            cursor.execute(
                'SELECT COUNT(*) FROM device_activations WHERE license_key = ?',
                (lic['license_key'],)
            )
            lic['active_devices'] = cursor.fetchone()[0]
        
        return {
            'licenses': licenses,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page
        }


def revoke_license(license_key: str, reason: str = None) -> bool:
    """Revoke a license"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE licenses 
            SET revoked = 1, revoked_at = ?, revoked_reason = ?
            WHERE license_key = ? AND revoked = 0
        ''', (datetime.now().isoformat(), reason, license_key))
        return cursor.rowcount > 0


def extend_license(license_key: str, days: int) -> bool:
    """Extend license expiration"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT expires_at FROM licenses WHERE license_key = ?', (license_key,))
        row = cursor.fetchone()
        if not row:
            return False
        
        current_expiry = datetime.fromisoformat(row['expires_at']) if row['expires_at'] else datetime.now()
        if current_expiry < datetime.now():
            current_expiry = datetime.now()
        
        new_expiry = current_expiry + timedelta(days=days)
        
        cursor.execute(
            'UPDATE licenses SET expires_at = ? WHERE license_key = ?',
            (new_expiry.isoformat(), license_key)
        )
        return cursor.rowcount > 0


def reactivate_license(license_key: str) -> bool:
    """Reactivate a revoked license"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE licenses 
            SET revoked = 0, revoked_at = NULL, revoked_reason = NULL
            WHERE license_key = ?
        ''', (license_key,))
        return cursor.rowcount > 0


def reset_device_activations(license_key: str) -> int:
    """Reset all device activations for a license"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'DELETE FROM device_activations WHERE license_key = ?',
            (license_key,)
        )
        return cursor.rowcount


def get_device_activations(license_key: str) -> List[Dict]:
    """Get all device activations for a license"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM device_activations WHERE license_key = ? ORDER BY activated_at DESC',
            (license_key,)
        )
        return [dict(row) for row in cursor.fetchall()]


def validate_license(license_key: str, device_id: str = None) -> Dict:
    """Validate a license key (for client validation API)"""
    license_data = get_license(license_key)
    
    if not license_data:
        return {'valid': False, 'error': 'License not found'}
    
    if license_data['revoked']:
        return {'valid': False, 'error': 'License has been revoked'}
    
    if license_data['expires_at']:
        expires = datetime.fromisoformat(license_data['expires_at'])
        if expires < datetime.now():
            return {'valid': False, 'error': 'License has expired'}
    
    if device_id:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT COUNT(*) FROM device_activations WHERE license_key = ?',
                (license_key,)
            )
            active_count = cursor.fetchone()[0]
            
            cursor.execute(
                'SELECT * FROM device_activations WHERE license_key = ? AND device_id = ?',
                (license_key, device_id)
            )
            existing = cursor.fetchone()
            
            if not existing and active_count >= license_data['max_devices']:
                return {'valid': False, 'error': f'Maximum devices ({license_data["max_devices"]}) reached'}
            
            if existing:
                cursor.execute(
                    'UPDATE device_activations SET last_seen = ? WHERE license_key = ? AND device_id = ?',
                    (datetime.now().isoformat(), license_key, device_id)
                )
            else:
                cursor.execute('''
                    INSERT INTO device_activations (license_key, device_id, last_seen)
                    VALUES (?, ?, ?)
                ''', (license_key, device_id, datetime.now().isoformat()))
    
    return {
        'valid': True,
        'license_type': license_data['license_type'],
        'expires_at': license_data['expires_at'],
        'max_devices': license_data['max_devices']
    }


def get_license_stats() -> Dict:
    """Get license statistics for admin dashboard"""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM licenses')
        total = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM licenses WHERE revoked = 0 AND (expires_at IS NULL OR expires_at > datetime('now'))")
        active = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM licenses WHERE revoked = 0 AND expires_at <= datetime('now')")
        expired = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM licenses WHERE revoked = 1')
        revoked = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(DISTINCT device_id) FROM device_activations')
        total_devices = cursor.fetchone()[0]
        
        return {
            'total_licenses': total,
            'active_licenses': active,
            'expired_licenses': expired,
            'revoked_licenses': revoked,
            'total_devices': total_devices
        }


def add_audit_log(action: str, license_key: str = None, admin_user: str = None, 
                  details: str = None, ip_address: str = None):
    """Add entry to audit log"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO audit_log (action, license_key, admin_user, details, ip_address)
            VALUES (?, ?, ?, ?, ?)
        ''', (action, license_key, admin_user, details, ip_address))


init_database()
