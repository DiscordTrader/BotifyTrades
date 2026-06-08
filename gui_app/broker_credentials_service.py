"""
Broker Credentials Service
Handles encrypted storage and retrieval of broker credentials for all supported brokers.
Allows the application to start without config.ini and manage all credentials through the GUI.
"""
import json
from typing import Optional, Dict, Any
from .config_service import save_config, load_config, encrypt_value, decrypt_value


BROKER_STATUS = {
    'discord': {'connected': False, 'status': 'disconnected', 'error': None, 'account_info': None},
    'webull_live': {'connected': False, 'status': 'disconnected', 'error': None, 'account_info': None},
    'webull_paper': {'connected': False, 'status': 'disconnected', 'error': None, 'account_info': None},
    'alpaca_live': {'connected': False, 'status': 'disconnected', 'error': None, 'account_info': None},
    'alpaca_paper': {'connected': False, 'status': 'disconnected', 'error': None, 'account_info': None},
    'ibkr_live': {'connected': False, 'status': 'disconnected', 'error': None, 'account_info': None},
    'ibkr_paper': {'connected': False, 'status': 'disconnected', 'error': None, 'account_info': None},
    'tastytrade_live': {'connected': False, 'status': 'disconnected', 'error': None, 'account_info': None},
    'tastytrade_paper': {'connected': False, 'status': 'disconnected', 'error': None, 'account_info': None},
    'robinhood': {'connected': False, 'status': 'disconnected', 'error': None, 'account_info': None},
    'schwab': {'connected': False, 'status': 'disconnected', 'error': None, 'account_info': None},
    'trading212': {'connected': False, 'status': 'disconnected', 'error': None, 'account_info': None},
    'trading212_live': {'connected': False, 'status': 'disconnected', 'error': None, 'account_info': None},
    'trading212_paper': {'connected': False, 'status': 'disconnected', 'error': None, 'account_info': None},
    'webull_official': {'connected': False, 'status': 'disconnected', 'error': None, 'account_info': None},
    'webull_official_live': {'connected': False, 'status': 'disconnected', 'error': None, 'account_info': None},
    'webull_official_paper': {'connected': False, 'status': 'disconnected', 'error': None, 'account_info': None},
}


def get_broker_status(broker_id: str) -> Dict[str, Any]:
    """Get current connection status for a broker"""
    return BROKER_STATUS.get(broker_id, {'connected': False, 'status': 'unknown', 'error': 'Unknown broker'})


def set_broker_status(broker_id: str, connected: bool, status: str, error: str = None, account_info: dict = None):
    """Update broker connection status"""
    if broker_id in BROKER_STATUS:
        BROKER_STATUS[broker_id] = {
            'connected': connected,
            'status': status,
            'error': error,
            'account_info': account_info
        }


def get_all_broker_status() -> Dict[str, Dict[str, Any]]:
    """Get status of all brokers"""
    return BROKER_STATUS.copy()


def save_discord_credentials(token: str, allowed_authors: list = None, allowed_guilds: list = None):
    """Save Discord self-bot credentials"""
    save_config('discord_credentials', {
        'token': token,
        'allowed_authors': allowed_authors or [],
        'allowed_guilds': allowed_guilds or []
    })


def get_discord_credentials() -> Dict[str, Any]:
    """Get Discord credentials"""
    return load_config('discord_credentials') or {
        'token': '',
        'allowed_authors': [],
        'allowed_guilds': []
    }


def save_webull_credentials(
    email: str = '',
    password: str = '',
    trade_pin: str = '',
    device_id: str = '',
    access_token: str = '',
    refresh_token: str = '',
    token_expire: str = '',
    uuid: str = '',
    paper_mode: bool = True,
    region_id: str = '',
    zone_id: str = '',
    rzone: str = '',
    paper_account_enabled: bool = False,
    account_type: str = 'margin',
    sec_account_id: str = ''
):
    """Save Webull broker credentials (including region metadata for API v2)"""
    save_config('webull_credentials', {
        'email': email,
        'password': password,
        'trade_pin': trade_pin,
        'device_id': device_id,
        'access_token': access_token,
        'refresh_token': refresh_token,
        'token_expire': token_expire,
        'uuid': uuid,
        'paper_mode': paper_mode,
        'region_id': region_id,
        'zone_id': zone_id,
        'rzone': rzone,
        'paper_account_enabled': paper_account_enabled,
        'account_type': account_type,
        'sec_account_id': sec_account_id
    })


def update_webull_tokens(token_data: Dict[str, Any]):
    """Update only token fields in Webull credentials (preserves email/password)"""
    existing = get_webull_credentials()
    existing['access_token'] = token_data.get('access_token', existing.get('access_token', ''))
    existing['refresh_token'] = token_data.get('refresh_token', existing.get('refresh_token', ''))
    existing['token_expire'] = token_data.get('token_expire', existing.get('token_expire', ''))
    existing['uuid'] = token_data.get('uuid', existing.get('uuid', ''))
    if token_data.get('device_id'):
        existing['device_id'] = token_data.get('device_id')
    if token_data.get('region_id'):
        existing['region_id'] = token_data.get('region_id')
    if token_data.get('zone_id'):
        existing['zone_id'] = token_data.get('zone_id')
    if token_data.get('rzone'):
        existing['rzone'] = token_data.get('rzone')
    save_config('webull_credentials', existing)


def get_webull_credentials() -> Dict[str, Any]:
    """Get Webull credentials (including region metadata for API v2)"""
    defaults = {
        'email': '',
        'password': '',
        'trade_pin': '',
        'device_id': '',
        'access_token': '',
        'refresh_token': '',
        'token_expire': '',
        'uuid': '',
        'paper_mode': True,
        'region_id': '',
        'zone_id': '',
        'rzone': '',
        'paper_account_enabled': False,
        'account_type': 'margin',
        'sec_account_id': ''
    }
    creds = load_config('webull_credentials') or {}
    for key, default_val in defaults.items():
        if key not in creds:
            creds[key] = default_val
    return creds


def webull_credentials_adapter(action: str, data: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
    """
    Adapter for WebullAuth to access credentials storage.
    
    Args:
        action: 'get' to retrieve, 'save' to update tokens
        data: Token data when saving
        
    Returns:
        Credentials dict when getting, None when saving
    """
    if action == 'get':
        return get_webull_credentials()
    elif action == 'save' and data:
        update_webull_tokens(data)
        return None
    return None


def save_alpaca_credentials(
    api_key: str = '',
    secret_key: str = '',
    paper_mode: bool = True
):
    """Save Alpaca broker credentials"""
    save_config('alpaca_credentials', {
        'api_key': api_key,
        'secret_key': secret_key,
        'paper_mode': paper_mode
    })


def get_alpaca_credentials() -> Dict[str, Any]:
    """Get Alpaca credentials"""
    return load_config('alpaca_credentials') or {
        'api_key': '',
        'secret_key': '',
        'paper_mode': True
    }


def save_ibkr_credentials(
    host: str = '127.0.0.1',
    port_live: int = 7496,
    port_paper: int = 7497,
    client_id: int = 1,
    paper_mode: bool = True
):
    """Save Interactive Brokers credentials"""
    save_config('ibkr_credentials', {
        'host': host,
        'port_live': port_live,
        'port_paper': port_paper,
        'client_id': client_id,
        'paper_mode': paper_mode
    })


def get_ibkr_credentials() -> Dict[str, Any]:
    """Get IBKR credentials"""
    return load_config('ibkr_credentials') or {
        'host': '127.0.0.1',
        'port_live': 7496,
        'port_paper': 7497,
        'client_id': 1,
        'paper_mode': True
    }


def save_tastytrade_credentials(
    username: str = '',
    password: str = '',
    client_secret: str = '',
    refresh_token: str = '',
    paper_mode: bool = True
):
    """Save Tastytrade broker credentials (OAuth2 or legacy)"""
    existing = load_config('tastytrade_credentials') or {}
    save_config('tastytrade_credentials', {
        'username': username,
        'password': password,
        'client_secret': client_secret,
        'refresh_token': refresh_token,
        'paper_mode': paper_mode,
        'account_number_live': existing.get('account_number_live', ''),
        'account_number_paper': existing.get('account_number_paper', ''),
    })


def save_tastytrade_account_number(account_number: str, is_paper: bool = False):
    """Save selected Tastytrade account number for a specific mode"""
    existing = load_config('tastytrade_credentials') or {}
    key = 'account_number_paper' if is_paper else 'account_number_live'
    existing[key] = account_number
    save_config('tastytrade_credentials', existing)


def get_tastytrade_credentials() -> Dict[str, Any]:
    """Get Tastytrade credentials"""
    creds = load_config('tastytrade_credentials') or {}
    defaults = {
        'username': '',
        'password': '',
        'client_secret': '',
        'refresh_token': '',
        'paper_mode': True,
        'account_number_live': '',
        'account_number_paper': '',
    }
    if 'account_number' in creds and 'account_number_live' not in creds:
        creds['account_number_live'] = creds.pop('account_number', '')
    for k, v in defaults.items():
        creds.setdefault(k, v)
    return creds


def clear_tastytrade_credentials():
    """Clear Tastytrade credentials"""
    save_config('tastytrade_credentials', {
        'username': '',
        'password': '',
        'client_secret': '',
        'refresh_token': '',
        'paper_mode': True,
        'account_number_live': '',
        'account_number_paper': '',
    })
    set_broker_status('tastytrade_live', False, 'disconnected')
    set_broker_status('tastytrade_paper', False, 'disconnected')


def save_robinhood_credentials(
    username: str = '',
    password: str = '',
    totp_secret: str = '',
    device_token: str = ''
):
    """Save Robinhood broker credentials"""
    save_config('robinhood_credentials', {
        'username': username,
        'password': password,
        'totp_secret': totp_secret,
        'device_token': device_token
    })


def get_robinhood_credentials() -> Dict[str, Any]:
    """Get Robinhood credentials"""
    return load_config('robinhood_credentials') or {
        'username': '',
        'password': '',
        'totp_secret': '',
        'device_token': ''
    }


def clear_robinhood_credentials():
    """Clear Robinhood credentials"""
    save_config('robinhood_credentials', {
        'username': '',
        'password': '',
        'totp_secret': '',
        'device_token': ''
    })
    set_broker_status('robinhood', False, 'disconnected')


def save_schwab_credentials(
    client_id: str = '',
    client_secret: str = '',
    redirect_uri: str = 'https://127.0.0.1',
    dry_run: bool = False
):
    """Save Charles Schwab broker credentials (OAuth2)"""
    save_config('schwab_credentials', {
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'dry_run': dry_run
    })


def get_schwab_credentials() -> Dict[str, Any]:
    """Get Charles Schwab credentials"""
    return load_config('schwab_credentials') or {
        'client_id': '',
        'client_secret': '',
        'redirect_uri': 'https://127.0.0.1',
        'dry_run': False
    }


def clear_schwab_credentials():
    """Clear Charles Schwab credentials"""
    save_config('schwab_credentials', {
        'client_id': '',
        'client_secret': '',
        'redirect_uri': 'https://127.0.0.1',
        'dry_run': False
    })


def get_trading212_credentials() -> Dict[str, Any]:
    return load_config('trading212_credentials') or {
        'api_key': '',
        'api_secret': '',
        'environment': 'demo',
    }


def save_trading212_credentials(api_key: str, api_secret: str = '', environment: str = 'demo'):
    save_config('trading212_credentials', {
        'api_key': api_key,
        'api_secret': api_secret,
        'environment': environment,
    })


def clear_trading212_credentials():
    save_config('trading212_credentials', {
        'api_key': '',
        'api_secret': '',
        'environment': 'demo',
    })


def get_webull_official_credentials() -> Dict[str, Any]:
    creds = load_config('webull_official_credentials') or {}
    defaults = {
        'app_key': '',
        'app_secret': '',
        'environment': 'production',
        'paper_mode': False,
        'account_id': '',
        'account_type': 'MARGIN',
    }
    for k, v in defaults.items():
        creds.setdefault(k, v)
    return creds


def save_webull_official_credentials(app_key: str, app_secret: str, environment: str = 'production',
                                     paper_mode: bool = False, account_id: str = '',
                                     account_type: str = 'MARGIN'):
    save_config('webull_official_credentials', {
        'app_key': app_key,
        'app_secret': app_secret,
        'environment': environment,
        'paper_mode': paper_mode,
        'account_id': account_id,
        'account_type': account_type,
    })


def clear_webull_official_credentials():
    save_config('webull_official_credentials', {
        'app_key': '',
        'app_secret': '',
        'environment': 'production',
        'paper_mode': False,
        'account_id': '',
        'account_type': 'MARGIN',
    })
    set_broker_status('webull_official', False, 'disconnected')


def save_api_keys_extended(
    openai: str = '',
    alpha_vantage: str = '',
    finnhub: str = '',
    license_key: str = '',
    anthropic: str = '',
    gemini: str = ''
):
    """Save all API keys including license"""
    save_config('api_keys_extended', {
        'openai': openai,
        'alpha_vantage': alpha_vantage,
        'finnhub': finnhub,
        'license_key': license_key,
        'anthropic': anthropic,
        'gemini': gemini
    })


def get_api_keys_extended() -> Dict[str, Any]:
    """Get all API keys"""
    defaults = {
        'openai': '',
        'alpha_vantage': '',
        'finnhub': '',
        'license_key': '',
        'anthropic': '',
        'gemini': ''
    }
    stored = load_config('api_keys_extended')
    if stored:
        defaults.update(stored)
    return defaults


def get_all_credentials_for_startup() -> Dict[str, Any]:
    """
    Get all credentials formatted for bot startup.
    This replaces the need for config.ini for credentials.
    """
    discord = get_discord_credentials()
    webull = get_webull_credentials()
    alpaca = get_alpaca_credentials()
    ibkr = get_ibkr_credentials()
    tastytrade = get_tastytrade_credentials()
    api_keys = get_api_keys_extended()
    
    return {
        'DISCORD_USER_TOKEN': discord.get('token', ''),
        'ALLOWED_AUTHOR_IDS': discord.get('allowed_authors', []),
        'ALLOWED_GUILD_IDS': discord.get('allowed_guilds', []),
        
        'WEBULL_USERNAME': webull.get('email', ''),
        'WEBULL_PASSWORD': webull.get('password', ''),
        'WEBULL_TRADE_PIN': webull.get('trade_pin', ''),
        'WEBULL_DID': webull.get('device_id', ''),
        'WEBULL_ACCESS_TOKEN': webull.get('access_token', ''),
        'WEBULL_REFRESH_TOKEN': webull.get('refresh_token', ''),
        'WEBULL_PAPER_MODE': webull.get('paper_mode', True),
        
        'ALPACA_API_KEY': alpaca.get('api_key', ''),
        'ALPACA_SECRET_KEY': alpaca.get('secret_key', ''),
        'ALPACA_PAPER_MODE': alpaca.get('paper_mode', True),
        
        'IBKR_HOST': ibkr.get('host', '127.0.0.1'),
        'IBKR_PORT_LIVE': ibkr.get('port_live', 7496),
        'IBKR_PORT_PAPER': ibkr.get('port_paper', 7497),
        'IBKR_CLIENT_ID': ibkr.get('client_id', 1),
        'IBKR_PAPER_MODE': ibkr.get('paper_mode', True),
        
        'TASTYTRADE_USERNAME': tastytrade.get('username', ''),
        'TASTYTRADE_PASSWORD': tastytrade.get('password', ''),
        'TASTYTRADE_PAPER_MODE': tastytrade.get('paper_mode', True),
        
        'ROBINHOOD_USERNAME': get_robinhood_credentials().get('username', ''),
        'ROBINHOOD_PASSWORD': get_robinhood_credentials().get('password', ''),
        'ROBINHOOD_TOTP_SECRET': get_robinhood_credentials().get('totp_secret', ''),
        'ROBINHOOD_DEVICE_TOKEN': get_robinhood_credentials().get('device_token', ''),
        
        'TRADING212_API_KEY': get_trading212_credentials().get('api_key', ''),
        'TRADING212_API_SECRET': get_trading212_credentials().get('api_secret', ''),
        'TRADING212_ENVIRONMENT': get_trading212_credentials().get('environment', 'demo'),

        'WEBULL_OFFICIAL_APP_KEY': get_webull_official_credentials().get('app_key', ''),
        'WEBULL_OFFICIAL_APP_SECRET': get_webull_official_credentials().get('app_secret', ''),
        'WEBULL_OFFICIAL_ENVIRONMENT': get_webull_official_credentials().get('environment', 'production'),
        'WEBULL_OFFICIAL_PAPER_MODE': get_webull_official_credentials().get('paper_mode', False),
        'WEBULL_OFFICIAL_ACCOUNT_ID': get_webull_official_credentials().get('account_id', ''),

        'OPENAI_API_KEY': api_keys.get('openai', ''),
        'ALPHA_VANTAGE_API_KEY': api_keys.get('alpha_vantage', ''),
        'FINNHUB_API_KEY': api_keys.get('finnhub', ''),
        'LICENSE_KEY': api_keys.get('license_key', '')
    }


def has_any_credentials() -> bool:
    """Check if any credentials have been saved to the database"""
    discord = get_discord_credentials()
    webull = get_webull_credentials()
    alpaca = get_alpaca_credentials()
    
    return bool(
        discord.get('token') or
        webull.get('email') or
        webull.get('access_token') or
        alpaca.get('api_key')
    )


def get_enabled_brokers() -> Dict[str, bool]:
    """Get which brokers have credentials configured"""
    discord = get_discord_credentials()
    webull = get_webull_credentials()
    alpaca = get_alpaca_credentials()
    ibkr = get_ibkr_credentials()
    tastytrade = get_tastytrade_credentials()
    robinhood = get_robinhood_credentials()
    
    trading212 = get_trading212_credentials()
    
    return {
        'discord': bool(discord.get('token')),
        'webull': bool(webull.get('email') or webull.get('access_token')),
        'alpaca': bool(alpaca.get('api_key')),
        'ibkr': bool(ibkr.get('host')),
        'tastytrade': bool(tastytrade.get('username')),
        'robinhood': bool(robinhood.get('username')),
        'trading212': bool(trading212.get('api_key')),
        'webull_official': bool(get_webull_official_credentials().get('app_key'))
    }
