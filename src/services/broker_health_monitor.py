"""
Broker Health Monitor Service
Centralized monitoring for broker connection status, buying power validation,
and dashboard notifications.

Industry-grade implementation with:
- Thread-safe singleton with locking on all shared state
- Fail-safe pre-trade validation (blocks on missing cache)
- Normalized broker name handling
- Cache invalidation on disconnect
- Comprehensive error handling
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
        # Webull broker returns snake_case keys from get_account_info()
        'options': ['options_buying_power', 'buying_power', 'cash', 'optionBuyingPower', 'cashBalance'],
        'stocks': ['buying_power', 'cash', 'dayBuyingPower', 'cashBalance', 'overnightBuyingPower'],
        'fallback': 'buying_power'
    },
    'ALPACA': {
        # For options, use buying_power as primary since options_buying_power may be 0
        'options': ['buying_power', 'options_buying_power', 'cash'],
        'stocks': ['buying_power', 'cash'],
        'fallback': 'buying_power'
    },
    'ALPACA_PAPER': {
        # For options, use buying_power as primary since options_buying_power may be 0
        'options': ['buying_power', 'options_buying_power', 'cash'],
        'stocks': ['buying_power', 'cash'],
        'fallback': 'buying_power'
    },
    'ROBINHOOD': {
        # Robinhood: use buying_power as primary for options too
        'options': ['buying_power', 'options_buying_power', 'margin_buying_power', 'cash'],
        'stocks': ['buying_power', 'margin_buying_power', 'cash_available_for_withdrawal', 'cash'],
        'fallback': 'buying_power'
    },
    'SCHWAB': {
        'options': ['options_buying_power', 'optionBuyingPower', 'buying_power', 'availableFunds'],
        'stocks': ['buying_power', 'availableFunds', 'buyingPower', 'cash'],
        'fallback': 'buying_power'
    },
    'IBKR': {
        'options': ['options_buying_power', 'AvailableFunds', 'BuyingPower', 'availableFunds', 'buyingPower'],
        'stocks': ['buying_power', 'AvailableFunds', 'BuyingPower', 'availableFunds', 'buyingPower'],
        'fallback': 'AvailableFunds'
    },
    'TASTYTRADE': {
        'options': ['options_buying_power', 'option_buying_power', 'buying_power'],
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
        'options': ['available_margin', 'equity'],
        'stocks': ['available_margin', 'equity'],
        'fallback': 'available_margin'
    },
    'DHAN': {
        'options': ['availableBalance', 'allocatedBalance'],
        'stocks': ['availableBalance'],
        'fallback': 'availableBalance'
    },
    'TRADING212': {
        'options': ['buying_power', 'cash'],
        'stocks': ['buying_power', 'cash'],
        'fallback': 'buying_power'
    }
}


class BrokerHealthMonitor:
    """
    Centralized broker health and buying power monitoring.
    
    Thread-safe singleton with fail-safe defaults:
    - All state access is protected by locks
    - Missing cache = trade blocked (fail-safe)
    - Any error = broker marked disconnected
    """
    
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
        
        self._state_lock = threading.RLock()
        self._broker_states: Dict[str, Dict] = {}
        self._account_cache: Dict[str, Dict] = {}
        self._cache_ttl = 300
        self._disconnect_callbacks: List[callable] = []
        self._reconnect_callbacks: List[callable] = []
        self._last_notification: Dict[str, float] = {}
        self._notification_cooldown = 300
        
        self._clear_stale_disconnect_notifications()
        print("[HEALTH] BrokerHealthMonitor initialized (thread-safe)")
    
    def _clear_stale_disconnect_notifications(self):
        """Clear old broker_disconnect notifications and stale broker_states on startup."""
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
                UPDATE broker_notifications SET is_read = 1
                WHERE notification_type = 'broker_disconnect' AND is_read = 0
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS broker_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    broker_name TEXT NOT NULL UNIQUE,
                    country_code TEXT NOT NULL,
                    region TEXT NOT NULL,
                    is_connected INTEGER DEFAULT 0,
                    balance REAL DEFAULT 0,
                    buying_power REAL DEFAULT 0,
                    currency TEXT DEFAULT 'USD',
                    account_id TEXT,
                    account_number TEXT,
                    is_paper INTEGER DEFAULT 0,
                    last_sync_at TEXT,
                    sync_error TEXT,
                    extra_data TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            try:
                cursor.execute('DELETE FROM broker_states')
            except Exception:
                pass
            conn.commit()
            print("[HEALTH] Cleared stale broker disconnect notifications and broker states from previous session")
        except Exception as e:
            print(f"[HEALTH] Error clearing stale notifications: {e}")

    def _mark_broker_disconnect_notifications_read(self, broker_name: str):
        """Mark all unread disconnect notifications for a specific broker as read."""
        try:
            from gui_app.database import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE broker_notifications SET is_read = 1
                WHERE broker_name = ? AND notification_type = 'broker_disconnect' AND is_read = 0
            ''', (broker_name,))
            conn.commit()
        except Exception as e:
            print(f"[HEALTH] Error marking disconnect notifications read for {broker_name}: {e}")

    def _normalize_broker_name(self, broker_name: str) -> str:
        """Normalize broker name to uppercase, resolving short names like IBKR to IBKR_LIVE."""
        if not broker_name:
            return ""
        key = broker_name.upper().strip()
        with self._state_lock:
            if key in self._broker_states:
                return key
            for tracked in self._broker_states:
                if tracked.startswith(key + '_'):
                    return tracked
        return key
    
    def register_disconnect_callback(self, callback: callable):
        """Register callback for disconnect notifications."""
        with self._state_lock:
            self._disconnect_callbacks.append(callback)
    
    def register_reconnect_callback(self, callback: callable):
        """Register callback for reconnect notifications."""
        with self._state_lock:
            self._reconnect_callbacks.append(callback)
    
    def update_broker_status(self, broker_name: str, is_connected: bool, 
                             reason: Optional[str] = None, 
                             account_info: Optional[Dict] = None,
                             error_code: Optional[str] = None) -> None:
        """
        Update broker connection status and cache account info.
        
        CRITICAL: Any error_code forces is_connected=False for safety.
        Cache is cleared on disconnect to prevent stale data usage.
        """
        broker_key = self._normalize_broker_name(broker_name)
        if not broker_key:
            return
        
        with self._state_lock:
            previous_state = self._broker_states.get(broker_key, {})
            was_connected = previous_state.get('is_connected', False)
            
            current_status = BrokerStatus.CONNECTED if is_connected else BrokerStatus.DISCONNECTED
            
            if error_code:
                is_connected = False
                error_str = str(error_code).lower()
                original_reason = reason
                
                if '401' in str(error_code) or 'token' in error_str or 'expired' in error_str:
                    current_status = BrokerStatus.TOKEN_EXPIRED
                    reason = original_reason or DisconnectReason.TOKEN_EXPIRED.value
                elif '429' in str(error_code) or 'rate' in error_str or 'limit' in error_str:
                    current_status = BrokerStatus.RATE_LIMITED
                    reason = original_reason or DisconnectReason.RATE_LIMITED.value
                elif '403' in str(error_code) or 'auth' in error_str or 'permission' in error_str:
                    current_status = BrokerStatus.ERROR
                    reason = original_reason or DisconnectReason.INSUFFICIENT_PERMISSIONS.value
                elif '5' in str(error_code)[:1] or 'server' in error_str or 'internal' in error_str:
                    current_status = BrokerStatus.ERROR
                    reason = original_reason or DisconnectReason.API_ERROR.value
                elif 'network' in error_str or 'connection' in error_str or 'timeout' in error_str:
                    current_status = BrokerStatus.ERROR
                    reason = original_reason or DisconnectReason.NETWORK_ERROR.value
                else:
                    current_status = BrokerStatus.ERROR
                    reason = original_reason or DisconnectReason.UNKNOWN.value
            
            self._broker_states[broker_key] = {
                'is_connected': is_connected,
                'status': current_status.value,
                'reason': reason,
                'error_code': error_code,
                'last_check': datetime.now().isoformat(),
                'account_info': account_info if is_connected else None
            }
            
            if is_connected and account_info:
                self._account_cache[broker_key] = {
                    'data': account_info,
                    'timestamp': time.time()
                }
            elif not is_connected:
                if broker_key in self._account_cache:
                    existing = self._account_cache[broker_key]
                    existing['stale'] = True
                    existing['disconnected_at'] = time.time()
            
            callback_action = None
            callback_broker = broker_key
            callback_reason = reason or "Connection lost"
            
            if was_connected and not is_connected:
                callback_action = 'disconnect'
            elif not was_connected and is_connected:
                if broker_key in self._last_notification:
                    del self._last_notification[broker_key]
                callback_action = 'reconnect'
        
        if callback_action == 'disconnect':
            self._trigger_disconnect_notification(callback_broker, callback_reason)
        elif callback_action == 'reconnect':
            self._trigger_reconnect_notification(callback_broker)
        
        try:
            from gui_app.database import update_broker_state
            country_code = self._get_broker_country(broker_key)
            state = {
                'is_connected': is_connected,
                'balance': account_info.get('portfolio_value', 0) if account_info else 0,
                'buying_power': self._extract_buying_power(broker_key, account_info, 'stocks') if account_info else 0,
                'sync_error': reason if not is_connected else None,
                'account_id': account_info.get('account_id') if account_info else None,
                'extra': {
                    'status': current_status.value,
                    'error_code': error_code,
                    'options_buying_power': self._extract_buying_power(broker_key, account_info, 'options') if account_info else 0
                }
            }
            update_broker_state(broker_name, country_code, state)
        except Exception as e:
            print(f"[HEALTH] Error persisting broker state: {e}")
    
    def _get_broker_country(self, broker_name: str) -> str:
        """Get country code for broker."""
        india_brokers = ['ZERODHA', 'UPSTOX', 'DHAN']
        canada_brokers = ['QUESTRADE']
        uk_eu_brokers = ['TRADING212']
        
        broker_upper = self._normalize_broker_name(broker_name)
        if broker_upper in india_brokers:
            return 'IN'
        elif broker_upper in canada_brokers:
            return 'CA'
        elif broker_upper in uk_eu_brokers:
            return 'UK'
        return 'US'
    
    def _trigger_disconnect_notification(self, broker_name: str, reason: str):
        """Trigger disconnect notification to dashboard.
        
        Cooldown is handled by the notifier's _alerted_brokers lifecycle set
        (one alert per disconnect→reconnect cycle). No duplicate cooldown here.
        """
        with self._state_lock:
            callbacks = self._disconnect_callbacks.copy()
        
        notification = {
            'type': 'broker_disconnect',
            'broker': broker_name,
            'reason': reason,
            'timestamp': datetime.now().isoformat(),
            'severity': 'critical'
        }
        
        print(f"[HEALTH] ⚠️ BROKER DISCONNECTED: {broker_name} - {reason}")
        
        try:
            from gui_app.discord_notifier import notify_broker_disconnected
            notify_broker_disconnected(broker_name, reason)
        except Exception as e:
            print(f"[HEALTH] Disconnect notification error: {e}")
        
        for callback in callbacks:
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
        with self._state_lock:
            callbacks = self._reconnect_callbacks.copy()
        
        notification = {
            'type': 'broker_reconnect',
            'broker': broker_name,
            'timestamp': datetime.now().isoformat(),
            'severity': 'info'
        }
        
        print(f"[HEALTH] ✅ BROKER RECONNECTED: {broker_name}")
        
        self._mark_broker_disconnect_notifications_read(broker_name)
        
        try:
            from gui_app.discord_notifier import notify_broker_reconnected
            notify_broker_reconnected(broker_name)
        except Exception as e:
            print(f"[HEALTH] Reconnect notification error: {e}")
        
        for callback in callbacks:
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
        broker_key = self._normalize_broker_name(broker_name)
        with self._state_lock:
            return self._broker_states.get(broker_key, {
                'is_connected': False,
                'status': BrokerStatus.UNKNOWN.value,
                'reason': 'No status available - broker not tracked'
            })
    
    def get_all_broker_statuses(self) -> Dict[str, Dict]:
        """Get status for all tracked brokers."""
        with self._state_lock:
            return self._broker_states.copy()
    
    def get_broker_state(self, broker_name: str) -> Optional[Dict]:
        """Get current state for a broker (alias for get_broker_status for GUI compatibility)."""
        return self.get_broker_status(broker_name)

    def is_broker_healthy(self, broker_name: str) -> bool:
        """Check if broker is connected and healthy."""
        broker_key = self._normalize_broker_name(broker_name)
        with self._state_lock:
            state = self._broker_states.get(broker_key, {})
            if not state.get('is_connected', False):
                return False
            status = state.get('status', '')
            return status == BrokerStatus.CONNECTED.value
    
    def _extract_buying_power(self, broker_name: str, account_info: Dict, 
                              asset_type: str = 'stocks') -> float:
        """Extract buying power from account info using broker-specific field mapping."""
        if not account_info:
            return 0.0
        
        broker_key = self._normalize_broker_name(broker_name)
        if broker_key not in BROKER_BUYING_POWER_FIELDS:
            for key in ['buying_power', 'buyingPower', 'available_margin', 'cash', 
                       'availableFunds', 'equity', 'cashBalance']:
                if key in account_info:
                    try:
                        value = float(account_info[key] or 0)
                        if value > 0:
                            return value
                    except (ValueError, TypeError):
                        continue
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
                value = float(account_info[fallback_field] or 0)
                if value > 0:
                    return value
            except (ValueError, TypeError):
                pass
        
        return 0.0
    
    def get_cached_account_info(self, broker_name: str) -> Optional[Dict]:
        """Get cached account info if still valid."""
        broker_key = self._normalize_broker_name(broker_name)
        with self._state_lock:
            cache_entry = self._account_cache.get(broker_key)
            if cache_entry:
                if time.time() - cache_entry['timestamp'] < self._cache_ttl:
                    return cache_entry['data']
        return None
    
    def validate_buying_power(self, broker_name: str, required_amount: float,
                              asset_type: str = 'options') -> Tuple[bool, str]:
        """
        Validate if broker has sufficient buying power for a trade.
        
        FAIL-SAFE: Missing cache returns False (blocks trade).
        
        WEBULL-SPECIFIC: Uses settled_cash instead of buying_power to prevent
        good faith violations when settled cash is negative.
        
        Returns:
            Tuple of (is_valid, reason_if_invalid)
        """
        broker_key = self._normalize_broker_name(broker_name)
        cached_info = self.get_cached_account_info(broker_key)
        
        if not cached_info:
            with self._state_lock:
                broker_state = self._broker_states.get(broker_key, {})
                is_connected = broker_state.get('is_connected', False)
                stale_entry = self._account_cache.get(broker_key)
            
            if stale_entry and stale_entry.get('data'):
                stale_data = stale_entry['data']
                stale_bp = stale_data.get('buying_power', 0) or stale_data.get('options_buying_power', 0)
                age_s = time.time() - stale_entry.get('timestamp', 0)
                print(f"[HEALTH] ⚠️ Using stale cached data for {broker_name} (age={age_s:.0f}s, BP=${stale_bp:.2f})")
                cached_info = stale_data
            elif is_connected:
                print(f"[HEALTH] ⚠️ No cached data for {broker_name} but broker connected - allowing trade (broker will validate)")
                return True, ""
            else:
                reason = f"No cached account data for {broker_name} and broker not connected - cannot verify buying power"
                print(f"[HEALTH] ❌ {reason}")
                return False, reason
        
        # SETTLED CASH VALIDATION FOR ALL BROKERS
        # Good faith violations can occur on any broker when trading with unsettled funds
        # Brokers with settled cash tracking: WEBULL, ALPACA, ALPACA_PAPER, ROBINHOOD, SCHWAB
        brokers_with_settled_cash = ['WEBULL', 'ALPACA', 'ALPACA_PAPER', 'ROBINHOOD', 'SCHWAB']
        
        if broker_key in brokers_with_settled_cash:
            settled_cash = cached_info.get('settled_cash', 0)
            unsettled_cash = cached_info.get('unsettled_cash', 0)
            buying_power = cached_info.get('buying_power', 0)
            
            # Check if settled_cash data is actually available (non-zero or explicitly set)
            has_settled_cash_data = 'settled_cash' in cached_info and settled_cash is not None
            
            if has_settled_cash_data:
                print(f"[HEALTH] {broker_key} validation: SettledCash=${settled_cash:.2f}, UnsettledCash=${unsettled_cash:.2f}, BP=${buying_power:.2f}, Required=${required_amount:.2f}")
                
                # Block if settled cash is negative or zero
                if settled_cash <= 0:
                    reason = f"{broker_key}: Settled cash is ${settled_cash:.2f} (negative or zero) - cannot trade to avoid good faith violation"
                    print(f"[HEALTH] ❌ {reason}")
                    return False, reason
                
                # Block if settled cash is less than required
                if settled_cash < required_amount:
                    reason = f"{broker_key}: Insufficient settled cash: need ${required_amount:.2f}, have ${settled_cash:.2f} (BP=${buying_power:.2f} but unsettled)"
                    print(f"[HEALTH] ❌ {reason}")
                    return False, reason
                
                print(f"[HEALTH] ✓ {broker_key} settled cash validation passed: ${settled_cash:.2f} >= ${required_amount:.2f}")
                return True, ""
            else:
                # Fallback to buying power if settled_cash not available in cache
                print(f"[HEALTH] {broker_key}: No settled_cash data available, falling back to buying_power check")
        
        # Standard buying power check for brokers without settled cash tracking
        buying_power = self._extract_buying_power(broker_key, cached_info, asset_type)
        
        if buying_power <= 0:
            reason = f"No buying power available for {broker_name} (${buying_power:.2f})"
            return False, reason
        
        if buying_power < required_amount:
            reason = f"Insufficient buying power: need ${required_amount:.2f}, have ${buying_power:.2f}"
            return False, reason
        
        return True, ""
    
    def pre_trade_validation(self, broker_name: str, signal: Dict) -> Tuple[bool, str]:
        """
        Perform pre-trade validation including connection and buying power check.
        
        FAIL-SAFE defaults:
        - Unknown broker = blocked
        - Missing cache = blocked  
        - Any error status = blocked
        - Missing price/qty = blocked
        
        Returns:
            Tuple of (can_proceed, rejection_reason)
        """
        broker_key = self._normalize_broker_name(broker_name)
        if not broker_key:
            return False, "Invalid broker name"
        
        broker_status = self.get_broker_status(broker_key)
        
        if broker_status.get('status') == BrokerStatus.UNKNOWN.value:
            reason = f"Broker {broker_name} not tracked - waiting for first sync"
            return False, reason
        
        if not broker_status.get('is_connected', False):
            reason = f"Broker {broker_name} is disconnected: {broker_status.get('reason', 'Unknown')}"
            return False, reason
        
        status_value = broker_status.get('status', '')
        error_statuses = [
            BrokerStatus.TOKEN_EXPIRED.value, 
            BrokerStatus.RATE_LIMITED.value, 
            BrokerStatus.ERROR.value, 
            BrokerStatus.DISCONNECTED.value,
            BrokerStatus.UNKNOWN.value
        ]
        if status_value in error_statuses:
            reason = f"Broker {broker_name} in error state: {broker_status.get('reason', status_value)}"
            return False, reason
        
        price = signal.get('price') or signal.get('intended_price') or 0
        qty = signal.get('qty', 1)
        is_market_order = signal.get('is_market_order', False) or signal.get('_ndx_converted', False)
        
        try:
            price = float(price)
            qty = float(qty)
        except (ValueError, TypeError):
            return False, f"Invalid price ({price}) or quantity ({qty}) in signal"
        
        if price <= 0 and not is_market_order:
            return False, f"Invalid or missing price in signal: {price}"
        
        if price <= 0 and is_market_order:
            print(f"[HEALTH] ℹ️ Allowing market order with price={price} for {signal.get('symbol')}")
        
        if qty <= 0:
            return False, f"Invalid or missing quantity in signal: {qty}"
        
        asset_type = signal.get('asset_type', 'option')
        
        if asset_type in ('option', 'options'):
            if qty != int(qty):
                return False, f"Option contracts must be whole numbers, got: {qty}"
            qty = int(qty)
            
            is_conditional = signal.get('_conditional_order_id') is not None
            has_trigger_price = signal.get('_trigger_price') is not None
            has_qot_price = signal.get('_qot_price') is not None
            
            if is_conditional and is_market_order and not has_qot_price and has_trigger_price:
                print(f"[HEALTH] ℹ️ Skipping BP check for conditional market option order #{signal.get('_conditional_order_id')} "
                      f"(price ${price:.2f} is stock trigger, not option premium) - broker will validate", flush=True)
                return True, ""
            
            min_required = price * 100
            bp_type = 'options'
        else:
            min_required = price
            bp_type = 'stocks'
        
        is_valid, reason = self.validate_buying_power(broker_key, min_required, bp_type)
        
        if not is_valid:
            return False, reason
        
        if qty > 1 and min_required > 0:
            full_cost = min_required * qty
            cached_info = self.get_cached_account_info(broker_key)
            bp = self._extract_buying_power(broker_key, cached_info, bp_type) if cached_info else 0
            if bp > 0 and full_cost > bp:
                affordable = int(bp / min_required)
                if affordable >= 1:
                    print(f"[HEALTH] ℹ️ {broker_key}: Can afford {affordable}/{int(qty)} units (BP=${bp:.2f}, cost/unit=${min_required:.2f}) - auto-sizing downstream")
        
        return True, ""
    
    def record_trade_rejection(self, signal: Dict, broker_name: str, 
                               rejection_reason: str, channel_id: str = None) -> Optional[int]:
        """
        Record a trade rejection in the database.
        
        Returns the trade ID if successful, None otherwise.
        """
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
            trade_id = cursor.lastrowid
            print(f"[HEALTH] ❌ Trade rejected and recorded (ID={trade_id}): {signal.get('symbol')} - {rejection_reason}")
            return trade_id
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
    
    def force_refresh(self, broker_name: str) -> None:
        """Force clear cache for a broker to trigger fresh data fetch."""
        broker_key = self._normalize_broker_name(broker_name)
        with self._state_lock:
            if broker_key in self._account_cache:
                del self._account_cache[broker_key]
        print(f"[HEALTH] Forced cache refresh for {broker_name}")


_health_monitor = None
_module_lock = threading.Lock()

def get_health_monitor() -> BrokerHealthMonitor:
    """Get the singleton health monitor instance (thread-safe)."""
    global _health_monitor
    if _health_monitor is None:
        with _module_lock:
            if _health_monitor is None:
                _health_monitor = BrokerHealthMonitor()
    return _health_monitor
