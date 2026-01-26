"""
Broker Health Monitor Service
Centralized monitoring for broker connection status, buying power validation,
and dashboard notifications.
"""
import time
import threading
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from enum import Enum


class BrokerStatus(Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    TOKEN_EXPIRED = "token_expired"
    RATE_LIMITED = "rate_limited"
    UNKNOWN = "unknown"


class DisconnectReason(Enum):
    TOKEN_EXPIRED = "Token expired - requires re-authentication"
    API_ERROR = "API communication error"
    AUTH_FAILED = "Authentication failed"
    RATE_LIMITED = "Rate limit exceeded"
    NETWORK_ERROR = "Network connection error"
    ACCOUNT_LOCKED = "Account locked or restricted"
    MAINTENANCE = "Broker maintenance"
    INSUFFICIENT_PERMISSIONS = "Insufficient API permissions"
    UNKNOWN = "Unknown error"


BROKER_BUYING_POWER_FIELDS = {
    'WEBULL': {
        'options': ['optionBuyingPower', 'cashBalance'],
        'stocks': ['dayBuyingPower', 'cashBalance', 'overnightBuyingPower'],
        'fallback': 'cashBalance'
    },
    'ALPACA': {
        'options': ['options_buying_power', 'buying_power'],
        'stocks': ['buying_power', 'cash'],
        'fallback': 'buying_power'
    },
    'ALPACA_PAPER': {
        'options': ['options_buying_power', 'buying_power'],
        'stocks': ['buying_power', 'cash'],
        'fallback': 'buying_power'
    },
    'ROBINHOOD': {
        'options': ['options_buying_power', 'margin_buying_power'],
        'stocks': ['buying_power', 'margin_buying_power', 'cash_available_for_withdrawal'],
        'fallback': 'buying_power'
    },
    'SCHWAB': {
        'options': ['optionBuyingPower', 'availableFunds'],
        'stocks': ['availableFunds', 'buyingPower'],
        'fallback': 'availableFunds'
    },
    'IBKR': {
        'options': ['AvailableFunds', 'BuyingPower'],
        'stocks': ['AvailableFunds', 'BuyingPower'],
        'fallback': 'AvailableFunds'
    },
    'TASTYTRADE': {
        'options': ['option_buying_power', 'buying_power'],
        'stocks': ['buying_power', 'cash_balance'],
        'fallback': 'buying_power'
    },
    'QUESTRADE': {
        'options': ['buyingPower', 'combinedBuyingPower'],
        'stocks': ['buyingPower', 'combinedBuyingPower'],
        'fallback': 'buyingPower'
    },
    'ZERODHA': {
        'options': ['available_margin', 'net'],
        'stocks': ['available_margin', 'net'],
        'fallback': 'available_margin'
    },
    'UPSTOX': {
        'options': ['available_margin', 'used_margin'],
        'stocks': ['available_margin'],
        'fallback': 'available_margin'
    },
    'DHAN': {
        'options': ['availableBalance', 'allocatedBalance'],
        'stocks': ['availableBalance'],
        'fallback': 'availableBalance'
    }
}


class BrokerHealthMonitor:
    """Centralized broker health and buying power monitoring."""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._broker_states: Dict[str, Dict] = {}
        self._account_cache: Dict[str, Dict] = {}
        self._cache_ttl = 30
        self._disconnect_callbacks: List[callable] = []
        self._reconnect_callbacks: List[callable] = []
        self._last_notification: Dict[str, float] = {}
        self._notification_cooldown = 300
        
        print("[HEALTH] BrokerHealthMonitor initialized")
    
    def register_disconnect_callback(self, callback: callable):
        """Register callback for disconnect notifications."""
        self._disconnect_callbacks.append(callback)
    
    def register_reconnect_callback(self, callback: callable):
        """Register callback for reconnect notifications."""
        self._reconnect_callbacks.append(callback)
    
    def update_broker_status(self, broker_name: str, is_connected: bool, 
                             reason: Optional[str] = None, 
                             account_info: Optional[Dict] = None,
                             error_code: Optional[str] = None) -> None:
        """Update broker connection status and cache account info."""
        previous_state = self._broker_states.get(broker_name, {})
        was_connected = previous_state.get('is_connected', False)
        
        current_status = BrokerStatus.CONNECTED if is_connected else BrokerStatus.DISCONNECTED
        
        if error_code:
            if '401' in str(error_code) or 'token' in str(error_code).lower() or 'expired' in str(error_code).lower():
                current_status = BrokerStatus.TOKEN_EXPIRED
                reason = DisconnectReason.TOKEN_EXPIRED.value
            elif '429' in str(error_code) or 'rate' in str(error_code).lower():
                current_status = BrokerStatus.RATE_LIMITED
                reason = DisconnectReason.RATE_LIMITED.value
            elif '403' in str(error_code):
                reason = DisconnectReason.INSUFFICIENT_PERMISSIONS.value
        
        self._broker_states[broker_name] = {
            'is_connected': is_connected,
            'status': current_status.value,
            'reason': reason,
            'error_code': error_code,
            'last_check': datetime.now().isoformat(),
            'account_info': account_info
        }
        
        if account_info:
            self._account_cache[broker_name] = {
                'data': account_info,
                'timestamp': time.time()
            }
        
        if was_connected and not is_connected:
            self._trigger_disconnect_notification(broker_name, reason or "Connection lost")
        elif not was_connected and is_connected:
            self._trigger_reconnect_notification(broker_name)
        
        try:
            from gui_app.database import update_broker_state
            country_code = self._get_broker_country(broker_name)
            state = {
                'is_connected': is_connected,
                'balance': account_info.get('portfolio_value', 0) if account_info else 0,
                'buying_power': self._extract_buying_power(broker_name, account_info, 'stocks') if account_info else 0,
                'sync_error': reason if not is_connected else None,
                'account_id': account_info.get('account_id') if account_info else None,
                'extra': {
                    'status': current_status.value,
                    'error_code': error_code,
                    'options_buying_power': self._extract_buying_power(broker_name, account_info, 'options') if account_info else 0
                }
            }
            update_broker_state(broker_name, country_code, state)
        except Exception as e:
            print(f"[HEALTH] Error persisting broker state: {e}")
    
    def _get_broker_country(self, broker_name: str) -> str:
        """Get country code for broker."""
        india_brokers = ['ZERODHA', 'UPSTOX', 'DHAN']
        canada_brokers = ['QUESTRADE']
        
        if broker_name.upper() in india_brokers:
            return 'IN'
        elif broker_name.upper() in canada_brokers:
            return 'CA'
        return 'US'
    
    def _trigger_disconnect_notification(self, broker_name: str, reason: str):
        """Trigger disconnect notification to dashboard."""
        current_time = time.time()
        last_notified = self._last_notification.get(broker_name, 0)
        
        if current_time - last_notified < self._notification_cooldown:
            return
        
        self._last_notification[broker_name] = current_time
        
        notification = {
            'type': 'broker_disconnect',
            'broker': broker_name,
            'reason': reason,
            'timestamp': datetime.now().isoformat(),
            'severity': 'critical'
        }
        
        print(f"[HEALTH] ⚠️ BROKER DISCONNECTED: {broker_name} - {reason}")
        
        for callback in self._disconnect_callbacks:
            try:
                callback(notification)
            except Exception as e:
                print(f"[HEALTH] Callback error: {e}")
        
        try:
            self._store_notification(notification)
        except:
            pass
    
    def _trigger_reconnect_notification(self, broker_name: str):
        """Trigger reconnect notification."""
        notification = {
            'type': 'broker_reconnect',
            'broker': broker_name,
            'timestamp': datetime.now().isoformat(),
            'severity': 'info'
        }
        
        print(f"[HEALTH] ✅ BROKER RECONNECTED: {broker_name}")
        
        for callback in self._reconnect_callbacks:
            try:
                callback(notification)
            except Exception as e:
                print(f"[HEALTH] Callback error: {e}")
    
    def _store_notification(self, notification: Dict):
        """Store notification in database for dashboard display."""
        try:
            from gui_app.database import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS broker_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    broker_name TEXT NOT NULL,
                    notification_type TEXT NOT NULL,
                    message TEXT,
                    severity TEXT DEFAULT 'info',
                    is_read INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                INSERT INTO broker_notifications (broker_name, notification_type, message, severity)
                VALUES (?, ?, ?, ?)
            ''', (
                notification['broker'],
                notification['type'],
                notification.get('reason', ''),
                notification.get('severity', 'info')
            ))
            conn.commit()
        except Exception as e:
            print(f"[HEALTH] Error storing notification: {e}")
    
    def get_broker_status(self, broker_name: str) -> Dict:
        """Get current status for a broker."""
        return self._broker_states.get(broker_name, {
            'is_connected': False,
            'status': BrokerStatus.UNKNOWN.value,
            'reason': 'No status available'
        })
    
    def get_all_broker_statuses(self) -> Dict[str, Dict]:
        """Get status for all tracked brokers."""
        return self._broker_states.copy()
    
    def _extract_buying_power(self, broker_name: str, account_info: Dict, 
                              asset_type: str = 'stocks') -> float:
        """Extract buying power from account info using broker-specific field mapping."""
        if not account_info:
            return 0.0
        
        broker_key = broker_name.upper()
        if broker_key not in BROKER_BUYING_POWER_FIELDS:
            for key in ['buying_power', 'buyingPower', 'available_margin', 'cash']:
                if key in account_info:
                    try:
                        return float(account_info[key] or 0)
                    except:
                        pass
            return 0.0
        
        field_config = BROKER_BUYING_POWER_FIELDS[broker_key]
        fields_to_check = field_config.get(asset_type, [field_config['fallback']])
        
        for field in fields_to_check:
            if field in account_info:
                try:
                    value = float(account_info[field] or 0)
                    if value > 0:
                        return value
                except (ValueError, TypeError):
                    continue
        
        fallback_field = field_config.get('fallback')
        if fallback_field and fallback_field in account_info:
            try:
                return float(account_info[fallback_field] or 0)
            except:
                pass
        
        return 0.0
    
    def get_cached_account_info(self, broker_name: str) -> Optional[Dict]:
        """Get cached account info if still valid."""
        cache_entry = self._account_cache.get(broker_name)
        if cache_entry:
            if time.time() - cache_entry['timestamp'] < self._cache_ttl:
                return cache_entry['data']
        return None
    
    def validate_buying_power(self, broker_name: str, required_amount: float,
                              asset_type: str = 'options') -> Tuple[bool, str]:
        """
        Validate if broker has sufficient buying power for a trade.
        
        Returns:
            Tuple of (is_valid, reason_if_invalid)
        """
        cached_info = self.get_cached_account_info(broker_name)
        
        if not cached_info:
            return True, ""
        
        buying_power = self._extract_buying_power(broker_name, cached_info, asset_type)
        
        if buying_power <= 0:
            reason = f"No buying power available (${buying_power:.2f})"
            return False, reason
        
        if buying_power < required_amount:
            reason = f"Insufficient buying power: need ${required_amount:.2f}, have ${buying_power:.2f}"
            return False, reason
        
        return True, ""
    
    def pre_trade_validation(self, broker_name: str, signal: Dict) -> Tuple[bool, str]:
        """
        Perform pre-trade validation including buying power check.
        
        Returns:
            Tuple of (can_proceed, rejection_reason)
        """
        broker_status = self.get_broker_status(broker_name)
        if not broker_status.get('is_connected', False):
            reason = f"Broker {broker_name} is disconnected: {broker_status.get('reason', 'Unknown')}"
            return False, reason
        
        price = signal.get('price') or signal.get('intended_price') or 0
        qty = signal.get('qty', 1)
        asset_type = signal.get('asset_type', 'option')
        
        if asset_type == 'option':
            required_amount = price * 100 * qty
            bp_type = 'options'
        else:
            required_amount = price * qty
            bp_type = 'stocks'
        
        is_valid, reason = self.validate_buying_power(broker_name, required_amount, bp_type)
        
        if not is_valid:
            return False, reason
        
        return True, ""
    
    def record_trade_rejection(self, signal: Dict, broker_name: str, 
                               rejection_reason: str, channel_id: str = None):
        """Record a trade rejection in the database."""
        try:
            from gui_app.database import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO trades (
                    channel_id, direction, asset_type, symbol, strike, expiry, call_put,
                    quantity, intended_price, status, broker, rejection_reason, rejected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'FAILED', ?, ?, CURRENT_TIMESTAMP)
            ''', (
                channel_id or signal.get('channel_id'),
                signal.get('action', 'BTO'),
                signal.get('asset_type', 'option'),
                signal.get('symbol'),
                signal.get('strike'),
                signal.get('expiry'),
                signal.get('call_put'),
                signal.get('qty', 1),
                signal.get('price'),
                broker_name,
                rejection_reason
            ))
            conn.commit()
            print(f"[HEALTH] ❌ Trade rejected and recorded: {signal.get('symbol')} - {rejection_reason}")
            return cursor.lastrowid
        except Exception as e:
            print(f"[HEALTH] Error recording rejection: {e}")
            return None
    
    def get_unread_notifications(self, limit: int = 10) -> List[Dict]:
        """Get unread broker notifications for dashboard."""
        try:
            from gui_app.database import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, broker_name, notification_type, message, severity, created_at
                FROM broker_notifications
                WHERE is_read = 0
                ORDER BY created_at DESC
                LIMIT ?
            ''', (limit,))
            
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"[HEALTH] Error fetching notifications: {e}")
            return []
    
    def mark_notifications_read(self, notification_ids: List[int] = None):
        """Mark notifications as read."""
        try:
            from gui_app.database import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            
            if notification_ids:
                placeholders = ','.join('?' * len(notification_ids))
                cursor.execute(f'UPDATE broker_notifications SET is_read = 1 WHERE id IN ({placeholders})', 
                             notification_ids)
            else:
                cursor.execute('UPDATE broker_notifications SET is_read = 1')
            conn.commit()
        except Exception as e:
            print(f"[HEALTH] Error marking notifications read: {e}")


_health_monitor = None

def get_health_monitor() -> BrokerHealthMonitor:
    """Get the singleton health monitor instance."""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = BrokerHealthMonitor()
    return _health_monitor
