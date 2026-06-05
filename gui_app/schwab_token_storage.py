"""
Schwab Secure Token Storage
Stores refresh tokens securely using OS keyring with encrypted fallback.

Features:
- Primary: OS keyring (macOS Keychain, Windows Credential Manager, Linux Secret Service)
- Fallback: Local encrypted file using cryptography.fernet
- Multi-account support
- Token metadata stored in SQLite
"""

import os
import json
import hashlib
from typing import Optional, Dict, Any, List
from datetime import datetime
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

# Service name for keyring storage
KEYRING_SERVICE = "BotifyTrades-Schwab"
ENCRYPTED_TOKEN_FILE = "schwab_tokens.enc"
ENCRYPTION_SALT_FILE = ".schwab_salt"


class SecureTokenStorage:
    """
    Securely stores Schwab refresh tokens.
    
    Priority:
    1. OS Keyring (macOS Keychain, Windows Credential Manager, etc.)
    2. Encrypted local file (fallback)
    """
    
    def __init__(self, user_id: str = "default"):
        """
        Initialize secure token storage.
        
        Args:
            user_id: Identifier for the user/account (supports multi-account)
        """
        self.user_id = user_id
        self._keyring_available = self._check_keyring()
        self._fernet: Optional[Fernet] = None
        
        if self._keyring_available:
            print(f"[TOKEN STORAGE] Using OS keyring for secure storage")
        else:
            print(f"[TOKEN STORAGE] Using encrypted file storage (keyring unavailable)")
    
    def _check_keyring(self) -> bool:
        """Check if keyring is available and functional."""
        try:
            import keyring
            from keyring.errors import KeyringError, NoKeyringError
            
            # Try a test operation to verify keyring works
            test_key = f"{KEYRING_SERVICE}-test"
            keyring.set_password(KEYRING_SERVICE, test_key, "test")
            result = keyring.get_password(KEYRING_SERVICE, test_key)
            keyring.delete_password(KEYRING_SERVICE, test_key)
            
            return result == "test"
            
        except ImportError:
            print("[TOKEN STORAGE] keyring package not installed")
            return False
        except Exception as e:
            print(f"[TOKEN STORAGE] keyring not functional: {e}")
            return False
    
    def _get_fernet(self) -> Fernet:
        """Get or create Fernet encryption instance."""
        if self._fernet:
            return self._fernet
        
        # Get or create salt
        if os.path.exists(ENCRYPTION_SALT_FILE):
            with open(ENCRYPTION_SALT_FILE, 'rb') as f:
                salt = f.read()
        else:
            salt = os.urandom(16)
            with open(ENCRYPTION_SALT_FILE, 'wb') as f:
                f.write(salt)
        
        # Derive key from machine-specific data
        machine_id = self._get_machine_id()
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(machine_id.encode()))
        self._fernet = Fernet(key)
        
        return self._fernet
    
    def _get_machine_id(self) -> str:
        """Get a machine-specific identifier for encryption key derivation."""
        import platform
        import uuid
        
        # Combine multiple machine identifiers
        components = [
            platform.node(),
            platform.machine(),
            str(uuid.getnode()),
        ]
        
        # Add username for user-specific encryption
        try:
            import getpass
            components.append(getpass.getuser())
        except Exception:
            pass
        
        combined = "|".join(components)
        return hashlib.sha256(combined.encode()).hexdigest()
    
    def _keyring_key(self, account_id: str = "") -> str:
        """Generate keyring key for a specific account."""
        if account_id:
            return f"{self.user_id}:{account_id}"
        return self.user_id
    
    def save_refresh_token(
        self,
        refresh_token: str,
        account_id: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Save refresh token securely.
        
        Args:
            refresh_token: The Schwab refresh token to store
            account_id: Optional Schwab account ID (for multi-account)
            metadata: Optional metadata (stored in SQLite, not in keyring)
            
        Returns:
            True if saved successfully
        """
        key = self._keyring_key(account_id)
        
        try:
            if self._keyring_available:
                import keyring
                keyring.set_password(KEYRING_SERVICE, key, refresh_token)
                print(f"[TOKEN STORAGE] Saved refresh token to keyring for {key}")
            else:
                # Fallback to encrypted file
                self._save_encrypted(key, refresh_token)
                print(f"[TOKEN STORAGE] Saved refresh token to encrypted file for {key}")
            
            # Save metadata to SQLite
            if metadata:
                self._save_metadata(key, account_id, metadata)
            
            return True
            
        except Exception as e:
            print(f"[TOKEN STORAGE] Error saving refresh token: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_refresh_token(self, account_id: str = "") -> Optional[str]:
        """
        Retrieve refresh token.
        
        Args:
            account_id: Optional Schwab account ID
            
        Returns:
            Refresh token if found, None otherwise
        """
        key = self._keyring_key(account_id)
        
        try:
            if self._keyring_available:
                import keyring
                token = keyring.get_password(KEYRING_SERVICE, key)
                if token:
                    print(f"[TOKEN STORAGE] Retrieved refresh token from keyring for {key}")
                    return token
            
            # Try encrypted file fallback
            token = self._get_encrypted(key)
            if token:
                print(f"[TOKEN STORAGE] Retrieved refresh token from encrypted file for {key}")
                return token
            
            return None
            
        except Exception as e:
            print(f"[TOKEN STORAGE] Error getting refresh token: {e}")
            return None
    
    def delete_refresh_token(self, account_id: str = "") -> bool:
        """
        Delete refresh token.
        
        Args:
            account_id: Optional Schwab account ID
            
        Returns:
            True if deleted successfully
        """
        key = self._keyring_key(account_id)
        
        try:
            deleted = False
            
            if self._keyring_available:
                import keyring
                try:
                    keyring.delete_password(KEYRING_SERVICE, key)
                    deleted = True
                except keyring.errors.PasswordDeleteError:
                    pass
            
            # Also try to delete from encrypted file
            deleted = self._delete_encrypted(key) or deleted
            
            # Delete metadata
            self._delete_metadata(key)
            
            if deleted:
                print(f"[TOKEN STORAGE] Deleted refresh token for {key}")
            
            return deleted
            
        except Exception as e:
            print(f"[TOKEN STORAGE] Error deleting refresh token: {e}")
            return False
    
    def _save_encrypted(self, key: str, value: str):
        """Save value to encrypted file."""
        fernet = self._get_fernet()
        
        # Load existing data
        data = self._load_encrypted_file()
        data[key] = value
        
        # Encrypt and save
        encrypted = fernet.encrypt(json.dumps(data).encode())
        with open(ENCRYPTED_TOKEN_FILE, 'wb') as f:
            f.write(encrypted)
    
    def _get_encrypted(self, key: str) -> Optional[str]:
        """Get value from encrypted file."""
        data = self._load_encrypted_file()
        return data.get(key)
    
    def _delete_encrypted(self, key: str) -> bool:
        """Delete value from encrypted file."""
        data = self._load_encrypted_file()
        if key in data:
            del data[key]
            fernet = self._get_fernet()
            encrypted = fernet.encrypt(json.dumps(data).encode())
            with open(ENCRYPTED_TOKEN_FILE, 'wb') as f:
                f.write(encrypted)
            return True
        return False
    
    def _load_encrypted_file(self) -> Dict[str, str]:
        """Load and decrypt the token file."""
        if not os.path.exists(ENCRYPTED_TOKEN_FILE):
            return {}
        
        try:
            fernet = self._get_fernet()
            with open(ENCRYPTED_TOKEN_FILE, 'rb') as f:
                encrypted = f.read()
            
            decrypted = fernet.decrypt(encrypted)
            return json.loads(decrypted.decode())
            
        except Exception as e:
            print(f"[TOKEN STORAGE] Error decrypting token file: {e}")
            return {}
    
    def _save_metadata(self, key: str, account_id: str, metadata: Dict[str, Any]):
        """Save token metadata to SQLite."""
        try:
            from . import database as db
            
            # Create table if not exists
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS schwab_token_metadata (
                    key TEXT PRIMARY KEY,
                    account_id TEXT,
                    user_id TEXT,
                    scope TEXT,
                    token_created_at TEXT,
                    last_refreshed_at TEXT,
                    expires_at TEXT,
                    broker TEXT DEFAULT 'SCHWAB',
                    extra_data TEXT
                )
            ''')
            
            cursor.execute('''
                INSERT OR REPLACE INTO schwab_token_metadata 
                (key, account_id, user_id, scope, token_created_at, last_refreshed_at, expires_at, extra_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                key,
                account_id,
                self.user_id,
                metadata.get('scope', 'readonly'),
                metadata.get('created_at', datetime.now().isoformat()),
                metadata.get('last_refreshed', datetime.now().isoformat()),
                metadata.get('expires_at', ''),
                json.dumps(metadata.get('extra', {}))
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"[TOKEN STORAGE] Error saving metadata: {e}")
    
    def _delete_metadata(self, key: str):
        """Delete token metadata from SQLite."""
        try:
            from . import database as db
            
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM schwab_token_metadata WHERE key = ?', (key,))
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"[TOKEN STORAGE] Error deleting metadata: {e}")
    
    def get_metadata(self, account_id: str = "") -> Optional[Dict[str, Any]]:
        """Get token metadata from SQLite."""
        key = self._keyring_key(account_id)
        
        try:
            from . import database as db
            
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM schwab_token_metadata WHERE key = ?', (key,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                columns = ['key', 'account_id', 'user_id', 'scope', 'token_created_at', 
                          'last_refreshed_at', 'expires_at', 'broker', 'extra_data']
                return dict(zip(columns, row))
            
            return None
            
        except Exception as e:
            print(f"[TOKEN STORAGE] Error getting metadata: {e}")
            return None
    
    def list_accounts(self) -> List[Dict[str, Any]]:
        """List all stored Schwab accounts."""
        try:
            from . import database as db
            
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT key, account_id, user_id, last_refreshed_at, expires_at 
                FROM schwab_token_metadata 
                WHERE user_id = ?
            ''', (self.user_id,))
            rows = cursor.fetchall()
            conn.close()
            
            accounts = []
            for row in rows:
                accounts.append({
                    'key': row[0],
                    'account_id': row[1],
                    'user_id': row[2],
                    'last_refreshed': row[3],
                    'expires_at': row[4]
                })
            
            return accounts
            
        except Exception as e:
            print(f"[TOKEN STORAGE] Error listing accounts: {e}")
            return []


# Singleton instance
_storage: Optional[SecureTokenStorage] = None


def get_secure_storage(user_id: str = "default") -> SecureTokenStorage:
    """Get or create the secure token storage singleton."""
    global _storage
    if _storage is None or _storage.user_id != user_id:
        _storage = SecureTokenStorage(user_id)
    return _storage
