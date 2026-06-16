"""
Configuration Service
Handles encrypted storage and retrieval of credentials
"""
import os
import json
import base64
import hashlib
from cryptography.fernet import Fernet
from pathlib import Path
from typing import Optional, Dict, Any

_cached_cipher = None

def get_encryption_key():
    """Get encryption key - maintains backward compatibility while supporting portability.
    
    Priority order:
    1. ENCRYPTION_KEY environment variable (direct override)
    2. .encryption_key file (existing installations - backward compatible)
    3. Derive from LICENSE_KEY (new installations - portable across machines)
    4. Generate new key (last resort, will create .encryption_key file)
    """
    encryption_key_env = os.environ.get('ENCRYPTION_KEY', '')
    
    if encryption_key_env:
        try:
            return base64.urlsafe_b64decode(encryption_key_env)
        except Exception:
            pass
    
    key_file = Path.cwd() / '.encryption_key'
    if key_file.exists():
        try:
            with open(key_file, 'rb') as f:
                key = f.read()
                if key and len(key) >= 32:
                    return key
        except Exception:
            pass
    
    license_key = os.environ.get('LICENSE_KEY', '')
    if license_key and len(license_key) >= 8:
        derived = hashlib.sha256(f"botify_creds_{license_key}".encode()).digest()
        return base64.urlsafe_b64encode(derived)
    
    key = Fernet.generate_key()
    try:
        with open(key_file, 'wb') as f:
            f.write(key)
        print("[CONFIG] ⚠️ Generated new encryption key. For portable credentials, set LICENSE_KEY environment variable.")
    except Exception:
        print("[CONFIG] ⚠️ Could not save encryption key file")
    return key


def get_cipher():
    """Get or create cached Fernet cipher instance."""
    global _cached_cipher
    if _cached_cipher is None:
        _cached_cipher = Fernet(get_encryption_key())
    return _cached_cipher


def reset_cipher():
    """Reset cipher cache (call if LICENSE_KEY changes)."""
    global _cached_cipher
    _cached_cipher = None


cipher = get_cipher()


def encrypt_value(value: str) -> bytes:
    """Encrypt a configuration value"""
    return cipher.encrypt(value.encode())


def decrypt_value(encrypted: bytes, config_key: str = None) -> str:
    """Decrypt a configuration value.
    
    Args:
        encrypted: The encrypted bytes to decrypt
        config_key: Optional key name for logging purposes
        
    Returns:
        Decrypted string, or empty string if decryption fails
    """
    try:
        return cipher.decrypt(encrypted).decode()
    except Exception as e:
        if config_key:
            print(f"[CONFIG] ⚠️ Failed to decrypt '{config_key}': encryption key mismatch. Re-save credentials to fix.")
        return ""


def save_config(key: str, value: Any):
    """Save encrypted config to database"""
    from . import database as db
    
    # Convert value to JSON string
    json_value = json.dumps(value)
    
    # Encrypt
    encrypted = encrypt_value(json_value)
    
    # Save to database
    conn = db.get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO config (key, value_encrypted)
        VALUES (?, ?)
    ''', (key, encrypted))
    
    conn.commit()


def load_config(key: str) -> Optional[Any]:
    """Load and decrypt config from database"""
    from . import database as db
    
    conn = db.get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT value_encrypted FROM config WHERE key = ?', (key,))
    row = cursor.fetchone()
    
    if row:
        decrypted = decrypt_value(row[0], config_key=key)
        if not decrypted:
            return None
        try:
            return json.loads(decrypted)
        except Exception:
            return decrypted
    
    return None


def get_all_config() -> Dict[str, Any]:
    """Get all configuration (decrypted)"""
    from . import database as db
    
    conn = db.get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT key, value_encrypted FROM config')
    
    config = {}
    for row in cursor.fetchall():
        key = row[0]
        decrypted = decrypt_value(row[1], config_key=key)
        if not decrypted:
            continue
        try:
            config[key] = json.loads(decrypted)
        except Exception:
            config[key] = decrypted
    
    return config


# Convenience functions for common configs
def save_discord_config(token: str, allowed_authors: list = None, allowed_guilds: list = None):
    """Save Discord configuration"""
    save_config('discord', {
        'token': token,
        'allowed_authors': allowed_authors or [],
        'allowed_guilds': allowed_guilds or []
    })


def save_webull_config(email: str, password: str, did: str, access_token: str = '', refresh_token: str = '', paper_trading: bool = True):
    """Save Webull configuration"""
    save_config('webull', {
        'email': email,
        'password': password,
        'did': did,
        'access_token': access_token,
        'refresh_token': refresh_token,
        'paper_trading': paper_trading
    })


def save_api_keys(openai: str = '', alpha_vantage: str = '', finnhub: str = ''):
    """Save API keys"""
    save_config('api_keys', {
        'openai': openai,
        'alpha_vantage': alpha_vantage,
        'finnhub': finnhub
    })


def save_discord_notifications(webhook_url: str = '', channel_id: str = '', enabled: bool = True):
    """Save Discord notification webhook settings"""
    save_config('discord_notifications', {
        'webhook_url': webhook_url,
        'channel_id': channel_id,
        'enabled': enabled
    })


def get_discord_notifications() -> dict:
    """Get Discord notification settings"""
    return load_config('discord_notifications') or {
        'webhook_url': '',
        'channel_id': '',
        'enabled': True
    }


# AI Provider settings
AI_PROVIDERS = ['claude', 'openai', 'gemini', 'disabled']

AI_PROVIDER_DEFAULT_MODELS = {
    'claude': 'claude-haiku-4-5-20251001',
    'gemini': 'gemini-2.0-flash',
    'openai': 'gpt-4o-mini',
}

# Bare prefixes ('o1', 'o3', 'o4') already subsume hyphenated variants via startswith.
AI_PROVIDER_MODEL_PREFIXES = {
    'claude': ('claude-',),
    'gemini': ('gemini-',),
    'openai': ('gpt-', 'o1', 'o3', 'o4'),
}

def save_ai_provider(provider: str):
    if provider not in AI_PROVIDERS:
        provider = 'claude'
    save_config('ai_provider', provider)


def get_ai_provider() -> str:
    provider = load_config('ai_provider')
    if provider == 'replit_ai':
        return 'disabled'
    if provider not in AI_PROVIDERS:
        return 'claude'
    return provider
