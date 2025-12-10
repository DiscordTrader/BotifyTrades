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
import json
import base64
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from contextlib import contextmanager

LICENSE_DB_PATH = 'license_server.db'

DEFAULT_OFFLINE_GRACE_HOURS = 48


def get_rsa_private_key() -> Optional[str]:
    """Get RSA private key from environment variable.
    
    SECURITY: The private key must be stored in RSA_PRIVATE_KEY environment variable.
    Never hardcode the private key in source code.
    """
    key = os.environ.get('RSA_PRIVATE_KEY')
    if not key:
        print("[LICENSE-SERVER] WARNING: RSA_PRIVATE_KEY not set - signed tokens disabled")
        return None
    
    if '\\n' in key:
        key = key.replace('\\n', '\n')
    
    return key


def create_signed_token(license_key: str, machine_id: str, expires_at: str, 
                       license_type: str, grace_hours: int = None) -> Optional[str]:
    """Create an RSA-signed token for offline validation.
    
    Token format: base64(payload).base64(signature)
    Requires RSA_PRIVATE_KEY environment variable to be set.
    """
    try:
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend
        
        if grace_hours is None:
            grace_hours = DEFAULT_OFFLINE_GRACE_HOURS
        
        private_key_pem = get_rsa_private_key()
        if not private_key_pem:
            return None
        
        private_key = serialization.load_pem_private_key(
            private_key_pem.encode(),
            password=None,
            backend=default_backend()
        )
        
        grace_expires = datetime.now() + timedelta(hours=grace_hours)
        
        payload = {
            'license_key': license_key,
            'machine_id': machine_id,
            'expires': expires_at,
            'license_type': license_type,
            'offline_grace_expires': grace_expires.isoformat(),
            'issued_at': datetime.now().isoformat()
        }
        
        payload_bytes = json.dumps(payload, sort_keys=True).encode('utf-8')
        
        signature = private_key.sign(
            payload_bytes,
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        
        payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode('utf-8').rstrip('=')
        signature_b64 = base64.urlsafe_b64encode(signature).decode('utf-8').rstrip('=')
        
        return f"{payload_b64}.{signature_b64}"
        
    except ImportError:
        print("[LICENSE-SERVER] Warning: cryptography not available - signed tokens disabled")
        return None
    except Exception as e:
        print(f"[LICENSE-SERVER] Error creating signed token: {e}")
        return None


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
                machine_info TEXT,
                FOREIGN KEY (license_key) REFERENCES licenses(license_key),
                UNIQUE(license_key, device_id)
            )
        ''')
        
        try:
            cursor.execute('ALTER TABLE device_activations ADD COLUMN machine_info TEXT')
        except:
            pass
        
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
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_user_id INTEGER NOT NULL,
                token TEXT UNIQUE NOT NULL,
                expires_at TEXT NOT NULL,
                used INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (admin_user_id) REFERENCES admin_users(id)
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
        
        cursor.execute("SELECT COUNT(*) FROM licenses WHERE revoked = 0 AND expires_at > datetime('now') AND expires_at <= datetime('now', '+7 days')")
        expiring_soon = cursor.fetchone()[0]
        
        return {
            'total_licenses': total,
            'active_licenses': active,
            'expired_licenses': expired,
            'revoked_licenses': revoked,
            'total_devices': total_devices,
            'expiring_soon': expiring_soon
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


def activate_license(license_key: str, machine_id: str, machine_info: Dict = None) -> Dict:
    """Activate a license on a device - called by client"""
    import json
    import base64
    import hmac
    import hashlib
    
    license_data = get_license(license_key)
    
    if not license_data:
        return {'success': False, 'is_valid': False, 'error': 'Invalid license key'}
    
    if license_data['revoked']:
        return {'success': False, 'is_valid': False, 'error': 'License has been revoked'}
    
    if license_data['expires_at']:
        expires = datetime.fromisoformat(license_data['expires_at'])
        if expires < datetime.now():
            return {'success': False, 'is_valid': False, 'error': 'License has expired'}
    
    with get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute(
            'SELECT COUNT(*) FROM device_activations WHERE license_key = ?',
            (license_key,)
        )
        active_count = cursor.fetchone()[0]
        
        cursor.execute(
            'SELECT * FROM device_activations WHERE license_key = ? AND device_id = ?',
            (license_key, machine_id)
        )
        existing = cursor.fetchone()
        
        if not existing and active_count >= license_data['max_devices']:
            return {'success': False, 'is_valid': False, 
                    'error': f'Maximum devices ({license_data["max_devices"]}) reached'}
        
        now = datetime.now()
        if existing:
            cursor.execute(
                'UPDATE device_activations SET last_seen = ?, machine_info = ? WHERE license_key = ? AND device_id = ?',
                (now.isoformat(), json.dumps(machine_info) if machine_info else None, license_key, machine_id)
            )
        else:
            cursor.execute('''
                INSERT INTO device_activations (license_key, device_id, activated_at, last_seen, machine_info)
                VALUES (?, ?, ?, ?, ?)
            ''', (license_key, machine_id, now.isoformat(), now.isoformat(), 
                  json.dumps(machine_info) if machine_info else None))
    
    days_remaining = 0
    expires_str = None
    if license_data['expires_at']:
        expires = datetime.fromisoformat(license_data['expires_at'])
        expires_str = expires.strftime('%Y-%m-%d %H:%M:%S')
        days_remaining = max(0, (expires - datetime.now()).days)
    
    customer_id = f"customer_{license_key[-8:]}"
    
    signed_payload = {
        'machine_id': machine_id,
        'customer_id': customer_id,
        'license_type': license_data['license_type'],
        'days_remaining': days_remaining,
        'expires': expires_str,
        'is_valid': True,
        'signed_at': now.isoformat(),
        'offline_grace_expires': (now + timedelta(hours=48)).isoformat()
    }
    
    payload_json = json.dumps(signed_payload, sort_keys=True)
    payload_b64 = base64.b64encode(payload_json.encode()).decode()
    signature = hmac.new(b'license_server_secret', payload_b64.encode(), hashlib.sha256).hexdigest()
    signed_token = f"{payload_b64}.{signature}"
    
    return {
        'success': True,
        'is_valid': True,
        'customer_id': customer_id,
        'license_type': license_data['license_type'],
        'days_remaining': days_remaining,
        'expires': expires_str,
        'message': 'License activated',
        'signed_token': signed_token
    }


def validate_license_for_client(license_key: str, machine_id: str) -> Dict:
    """Validate a license for client - returns client-compatible response with signed token"""
    license_data = get_license(license_key)
    
    if not license_data:
        return {'success': False, 'is_valid': False, 'error': 'Invalid license key'}
    
    if license_data['revoked']:
        return {'success': False, 'is_valid': False, 'error': 'License has been revoked'}
    
    if license_data['expires_at']:
        expires = datetime.fromisoformat(license_data['expires_at'])
        if expires < datetime.now():
            return {'success': False, 'is_valid': False, 'error': 'License has expired'}
    
    if machine_id:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE device_activations SET last_seen = ? WHERE license_key = ? AND device_id = ?',
                (datetime.now().isoformat(), license_key, machine_id)
            )
    
    days_remaining = 0
    expires_at = license_data['expires_at']
    if expires_at:
        expires = datetime.fromisoformat(expires_at)
        days_remaining = max(0, (expires - datetime.now()).days)
    
    signed_token = None
    if machine_id:
        signed_token = create_signed_token(
            license_key=license_key,
            machine_id=machine_id,
            expires_at=expires_at,
            license_type=license_data['license_type']
        )
    
    return {
        'success': True,
        'is_valid': True,
        'license_type': license_data['license_type'],
        'days_remaining': days_remaining,
        'expires': expires_at,
        'signed_token': signed_token
    }


def create_trial_license(machine_id: str, machine_info: Dict = None) -> Dict:
    """Create a trial license for a machine"""
    import json
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT license_key FROM device_activations WHERE device_id = ?',
            (machine_id,)
        )
        existing = cursor.fetchone()
        if existing:
            lic = get_license(existing['license_key'])
            if lic and lic['license_type'] == 'trial':
                return {'success': False, 'error': 'Trial already used on this device'}
    
    license_key = f"BT-TRIAL-{secrets.token_hex(4).upper()}"
    expires_at = (datetime.now() + timedelta(days=7)).isoformat()
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO licenses (license_key, license_type, max_devices, expires_at, notes)
            VALUES (?, 'trial', 1, ?, 'Auto-generated trial')
        ''', (license_key, expires_at))
        
        cursor.execute('''
            INSERT INTO device_activations (license_key, device_id, activated_at, last_seen, machine_info)
            VALUES (?, ?, ?, ?, ?)
        ''', (license_key, machine_id, datetime.now().isoformat(), datetime.now().isoformat(),
              json.dumps(machine_info) if machine_info else None))
    
    return {
        'success': True,
        'license_key': license_key,
        'expires_at': expires_at,
        'days_remaining': 7,
        'license_type': 'trial'
    }


def deactivate_device(license_key: str, machine_id: str) -> Dict:
    """Deactivate a device from a license"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'DELETE FROM device_activations WHERE license_key = ? AND device_id = ?',
            (license_key, machine_id)
        )
        if cursor.rowcount > 0:
            return {'success': True, 'message': 'Device deactivated'}
        return {'success': False, 'error': 'Device not found'}


def get_audit_logs(page: int = 1, per_page: int = 25, action: str = None, search: str = None) -> Dict:
    """Get paginated audit logs with filtering"""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        where_clauses = []
        params = []
        
        if action:
            where_clauses.append('action LIKE ?')
            params.append(f'%{action}%')
        
        if search:
            where_clauses.append('(license_key LIKE ? OR admin_user LIKE ? OR details LIKE ?)')
            params.extend([f'%{search}%', f'%{search}%', f'%{search}%'])
        
        where_sql = ' AND '.join(where_clauses) if where_clauses else '1=1'
        
        cursor.execute(f'SELECT COUNT(*) FROM audit_log WHERE {where_sql}', params)
        total = cursor.fetchone()[0]
        
        offset = (page - 1) * per_page
        cursor.execute(f'''
            SELECT id, action, license_key, admin_user, details, ip_address, created_at as timestamp
            FROM audit_log 
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        ''', params + [per_page, offset])
        
        logs = [dict(row) for row in cursor.fetchall()]
        
        return {
            'logs': logs,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page if total > 0 else 1
        }


def update_admin_password(username: str, new_password: str) -> bool:
    """Update admin password"""
    import bcrypt
    
    password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE admin_users SET password_hash = ? WHERE username = ?',
            (password_hash, username)
        )
        return cursor.rowcount > 0


def get_admin_by_email(email: str) -> Optional[Dict]:
    """Get admin user by email (case-insensitive)"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id, username, email FROM admin_users WHERE LOWER(email) = LOWER(?)', (email,))
        row = cursor.fetchone()
        return dict(row) if row else None


def create_password_reset_token(admin_user_id: int) -> str:
    """Create a password reset token for an admin user"""
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now() + timedelta(hours=1)).isoformat()
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM password_reset_tokens WHERE admin_user_id = ?', (admin_user_id,))
        cursor.execute('''
            INSERT INTO password_reset_tokens (admin_user_id, token, expires_at)
            VALUES (?, ?, ?)
        ''', (admin_user_id, token, expires_at))
    
    return token


def verify_reset_token(token: str) -> Optional[Dict]:
    """Verify a password reset token and return admin info if valid"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT prt.id, prt.admin_user_id, prt.expires_at, prt.used,
                   au.username, au.email
            FROM password_reset_tokens prt
            JOIN admin_users au ON au.id = prt.admin_user_id
            WHERE prt.token = ?
        ''', (token,))
        row = cursor.fetchone()
        
        if not row:
            return None
        
        data = dict(row)
        
        if data['used']:
            return None
        
        if datetime.fromisoformat(data['expires_at']) < datetime.now():
            return None
        
        return data


def use_reset_token(token: str, new_password: str) -> bool:
    """Use a reset token to change password"""
    token_data = verify_reset_token(token)
    if not token_data:
        return False
    
    new_hash = hash_password(new_password)
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE admin_users SET password_hash = ? WHERE id = ?',
            (new_hash, token_data['admin_user_id'])
        )
        cursor.execute(
            'UPDATE password_reset_tokens SET used = 1 WHERE token = ?',
            (token,)
        )
    
    return True


init_database()
