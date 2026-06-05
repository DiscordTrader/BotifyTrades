"""
Wizard Database Adapter
Interfaces between the Setup Wizard and the existing gui_app database
"""

import json
from typing import Dict, Any, List, Optional
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from gui_app.database import (
        get_connection, get_setting, save_setting, init_db
    )
    from gui_app.broker_credentials_service import (
        save_discord_credentials, get_discord_credentials,
        save_webull_credentials, get_webull_credentials,
        save_alpaca_credentials, get_alpaca_credentials,
        save_ibkr_credentials, get_ibkr_credentials,
        save_tastytrade_credentials, get_tastytrade_credentials,
        save_robinhood_credentials, get_robinhood_credentials
    )
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False


class WizardDatabaseAdapter:
    """Adapter to save wizard configuration to the existing database"""
    
    def __init__(self):
        self._ensure_db_initialized()
    
    def _ensure_db_initialized(self):
        """Ensure the database is initialized"""
        if DB_AVAILABLE:
            try:
                init_db()
            except Exception:
                pass
    
    def is_first_run(self) -> bool:
        """Check if this is the first time running the app"""
        if not DB_AVAILABLE:
            return True
        
        try:
            wizard_complete = get_setting('wizard_completed')
            return wizard_complete != 'true'
        except Exception:
            return True
    
    def mark_wizard_complete(self):
        """Mark the wizard as completed"""
        if DB_AVAILABLE:
            save_setting('wizard_completed', 'true')
    
    def save_wizard_config(self, data: Dict[str, Any]) -> bool:
        """Save all wizard configuration to the database"""
        if not DB_AVAILABLE:
            return False
        
        try:
            self._save_app_mode(data.get('app_mode', {}))
            self._save_discord_config(data.get('discord', {}))
            self._save_broker_config(data.get('brokers', {}), data.get('broker_credentials', {}))
            self._save_channel_config(data.get('channels', {}))
            self._save_risk_config(data.get('risk_management', {}))
            self._save_notification_config(data.get('notifications', {}))
            self._save_privacy_config(data.get('privacy', {}))
            
            self.mark_wizard_complete()
            return True
        except Exception as e:
            print(f"[WizardDB] Error saving config: {e}")
            return False
    
    def _save_app_mode(self, data: Dict[str, Any]):
        """Save app mode settings"""
        mode = data.get('mode', 'paper')
        
        save_setting('app_mode', mode)
        save_setting('risk_accepted', 'true' if data.get('risk_accepted') else 'false')
        
        if mode == 'live':
            save_setting('paper_trade', 'false')
        else:
            save_setting('paper_trade', 'true')
    
    def _save_discord_config(self, data: Dict[str, Any]):
        """Save Discord configuration"""
        token = data.get('token', '')
        guild_id = data.get('guild_id', '')
        allowed_authors = data.get('allowed_authors', [])
        
        if token:
            save_discord_credentials(
                token=token,
                allowed_authors=allowed_authors,
                allowed_guilds=[guild_id] if guild_id else []
            )
    
    def _save_broker_config(self, brokers: Dict[str, Any], credentials: Dict[str, Any]):
        """Save broker selection and credentials"""
        selected = brokers.get('selected_brokers', [])
        save_setting('selected_brokers', json.dumps(selected))
        
        for broker_id in selected:
            creds = credentials.get(broker_id, {})
            
            if broker_id == 'webull':
                existing_webull = get_webull_credentials()
                save_webull_credentials(
                    device_id=creds.get('device_id', ''),
                    access_token=creds.get('access_token', ''),
                    trade_pin=creds.get('trade_pin', ''),
                    paper_mode=creds.get('paper_trade', True),
                    account_type=existing_webull.get('account_type', 'margin')
                )
            elif broker_id == 'alpaca':
                save_alpaca_credentials(
                    api_key=creds.get('api_key', ''),
                    secret_key=creds.get('secret_key', ''),
                    paper_mode=creds.get('paper_trade', True)
                )
            elif broker_id == 'ibkr':
                paper_mode = creds.get('paper_trade', True)
                port = creds.get('port', 7497 if paper_mode else 7496)
                save_ibkr_credentials(
                    host=creds.get('host', '127.0.0.1'),
                    port_live=port if not paper_mode else 7496,
                    port_paper=port if paper_mode else 7497,
                    client_id=creds.get('client_id', 1),
                    paper_mode=paper_mode
                )
            elif broker_id == 'tastytrade':
                save_tastytrade_credentials(
                    username=creds.get('username', ''),
                    password=creds.get('password', ''),
                    client_secret=creds.get('client_secret', ''),
                    refresh_token=creds.get('refresh_token', ''),
                    paper_mode=creds.get('paper_trade', True)
                )
            elif broker_id == 'robinhood':
                save_robinhood_credentials(
                    username=creds.get('username', ''),
                    password=creds.get('password', ''),
                    totp_secret=creds.get('totp_secret', ''),
                    device_token=creds.get('device_token', '')
                )
    
    def _save_channel_config(self, data: Dict[str, Any]):
        """Save channel configuration"""
        channels = data.get('channels', [])
        
        if not channels:
            return
        
        conn = get_connection()
        cursor = conn.cursor()
        
        for ch in channels:
            discord_id = ch.get('channel_id')
            if not discord_id:
                continue
            
            execute_enabled = ch.get('execute_enabled', False)
            track_enabled = ch.get('track_enabled', False)
            
            if execute_enabled and track_enabled:
                category = 'EXECUTE'
            elif execute_enabled:
                category = 'EXECUTE'
            elif track_enabled:
                category = 'TRACK'
            else:
                category = 'EXECUTE'
            
            cursor.execute('''
                INSERT INTO channels (
                    discord_channel_id, name, category, 
                    execute_enabled, track_enabled, 
                    broker_override, is_active,
                    position_size_pct, tracking_position_size_pct
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(discord_channel_id) DO UPDATE SET
                    name = excluded.name,
                    category = excluded.category,
                    execute_enabled = excluded.execute_enabled,
                    track_enabled = excluded.track_enabled,
                    broker_override = excluded.broker_override,
                    is_active = 1,
                    position_size_pct = excluded.position_size_pct,
                    tracking_position_size_pct = excluded.tracking_position_size_pct
            ''', (
                discord_id,
                ch.get('channel_name', ''),
                category,
                1 if execute_enabled else 0,
                1 if track_enabled else 0,
                ch.get('broker_override'),
                ch.get('exec_position_size_pct', 5),
                ch.get('track_position_size_pct', 5)
            ))
        
        conn.commit()
    
    def _save_risk_config(self, data: Dict[str, Any]):
        """Save risk management settings"""
        save_setting('position_sizing_mode', data.get('position_sizing_mode', 'fixed_amount'))
        save_setting('risk_per_trade_amount', str(data.get('risk_per_trade_amount', 100)))
        save_setting('risk_per_trade_percent', str(data.get('risk_per_trade_percent', 2)))
        save_setting('max_position_size', str(data.get('max_position_size', 1000)))
        
        stop_loss_mode = data.get('stop_loss_mode', 'fixed_percentage')
        stop_loss_enabled = stop_loss_mode != 'none'
        save_setting('stop_loss_enabled', 'true' if stop_loss_enabled else 'false')
        save_setting('stop_loss_mode', stop_loss_mode)
        save_setting('stop_loss_percent', str(data.get('stop_loss_percent', 5)))
        
        profit_target_1 = data.get('profit_target_1', 20)
        take_profit_enabled = profit_target_1 > 0
        save_setting('take_profit_enabled', 'true' if take_profit_enabled else 'false')
        save_setting('profit_target_1_pct', str(profit_target_1))
        save_setting('profit_target_2_pct', str(data.get('profit_target_2', 50)))
        save_setting('profit_target_3_pct', str(data.get('profit_target_3', 100)))
        
        save_setting('trailing_stop_enabled', 'true' if data.get('trailing_stop_enabled') else 'false')
        save_setting('trailing_stop_percent', str(data.get('trailing_stop_percent', 3)))
        
        save_setting('max_daily_loss', str(data.get('max_daily_loss', 500)))
        save_setting('max_open_positions', str(data.get('max_open_positions', 5)))
        
        save_setting('kill_switch_enabled', 'true' if data.get('kill_switch_enabled') else 'false')
        save_setting('kill_switch_threshold', str(data.get('kill_switch_threshold', 1000)))
    
    def _save_notification_config(self, data: Dict[str, Any]):
        """Save notification settings"""
        save_setting('discord_notifications', 'true' if data.get('discord_enabled') else 'false')
        save_setting('desktop_notifications', 'true' if data.get('desktop_enabled') else 'false')
        save_setting('email_notifications', 'true' if data.get('email_enabled') else 'false')
        
        if data.get('email_address'):
            save_setting('notification_email', data.get('email_address', ''))
        
        save_setting('notify_on_trade', 'true' if data.get('notify_on_trade', True) else 'false')
        save_setting('notify_on_error', 'true' if data.get('notify_on_error', True) else 'false')
        save_setting('notify_on_profit', 'true' if data.get('notify_on_profit') else 'false')
    
    def _save_privacy_config(self, data: Dict[str, Any]):
        """Save privacy settings"""
        save_setting('analytics_enabled', 'true' if data.get('analytics_enabled') else 'false')
        save_setting('crash_reporting_enabled', 'true' if data.get('crash_reports_enabled') else 'false')
    
    def load_existing_config(self) -> Dict[str, Any]:
        """Load existing configuration for pre-populating the wizard"""
        if not DB_AVAILABLE:
            return {}
        
        config = {}
        
        try:
            mode = get_setting('app_mode', 'paper')
            config['app_mode'] = {
                'mode': mode,
                'risk_accepted': get_setting('risk_accepted') == 'true'
            }
            
            discord_creds = get_discord_credentials()
            config['discord'] = {
                'token': discord_creds.get('token', ''),
                'allowed_authors': discord_creds.get('allowed_authors', []),
                'allowed_guilds': discord_creds.get('allowed_guilds', [])
            }
            
            selected_brokers_json = get_setting('selected_brokers', '[]')
            selected_brokers = json.loads(selected_brokers_json) if selected_brokers_json else []
            config['brokers'] = {'selected_brokers': selected_brokers}
            
        except Exception as e:
            print(f"[WizardDB] Error loading config: {e}")
        
        return config


def check_first_run() -> bool:
    """Check if this is the first run"""
    adapter = WizardDatabaseAdapter()
    return adapter.is_first_run()


def get_wizard_adapter() -> WizardDatabaseAdapter:
    """Get a database adapter instance"""
    return WizardDatabaseAdapter()
