"""
Configuration Service
Handles encrypted storage and retrieval of credentials
"""
import json
import base64
from cryptography.fernet import Fernet
from pathlib import Path
from typing import Optional, Dict, Any

# Encryption key (should be machine-specific in production)
def get_encryption_key():
    """Get or create encryption key"""
    key_file = Path.cwd() / '.encryption_key'
    
    if key_file.exists():
        with open(key_file, 'rb') as f:
            return f.read()
    else:
        key = Fernet.generate_key()
        with open(key_file, 'wb') as f:
            f.write(key)
        return key


cipher = Fernet(get_encryption_key())


def encrypt_value(value: str) -> bytes:
    """Encrypt a configuration value"""
    return cipher.encrypt(value.encode())


def decrypt_value(encrypted: bytes) -> str:
    """Decrypt a configuration value"""
    try:
        return cipher.decrypt(encrypted).decode()
    except Exception:
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
        decrypted = decrypt_value(row[0])
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
        decrypted = decrypt_value(row[1])
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
AI_PROVIDERS = ['replit_ai', 'openai', 'disabled']

def save_ai_provider(provider: str):
    """Save AI provider preference.
    
    Options: 'replit_ai', 'openai', 'disabled'
    """
    if provider not in AI_PROVIDERS:
        provider = 'replit_ai'  # Default to Replit AI
    save_config('ai_provider', provider)


def get_ai_provider() -> str:
    """Get current AI provider preference.
    
    Returns: 'replit_ai', 'openai', or 'disabled'
    """
    provider = load_config('ai_provider')
    if provider not in AI_PROVIDERS:
        return 'replit_ai'  # Default to Replit AI
    return provider
