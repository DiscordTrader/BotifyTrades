"""
Connection Health Monitor - Industrial-grade connection monitoring for all services
Tracks Discord, Telegram, and Broker connections with disconnect detection and alerts
"""
import time
import threading
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, List, Any, Callable
from dataclasses import dataclass, field, asdict
import traceback

class ConnectionStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    RECONNECTING = "reconnecting"
    ERROR = "error"
    NOT_CONFIGURED = "not_configured"

class DisconnectReason(str, Enum):
    TOKEN_EXPIRED = "token_expired"
    TOKEN_INVALID = "token_invalid"
    RATE_LIMITED = "rate_limited"
    NETWORK_TIMEOUT = "network_timeout"
    NETWORK_ERROR = "network_error"
    AUTH_FAILED = "auth_failed"
    CREDENTIAL_REVOKED = "credential_revoked"
    WEBSOCKET_CLOSED = "websocket_closed"
    HEARTBEAT_FAILED = "heartbeat_failed"
    API_ERROR = "api_error"
    SESSION_EXPIRED = "session_expired"
    MAINTENANCE = "maintenance"
    UNKNOWN = "unknown"
    MANUAL_STOP = "manual_stop"

@dataclass
class ConnectionState:
    service_name: str
    service_type: str
    status: ConnectionStatus = ConnectionStatus.NOT_CONFIGURED
    last_connected: Optional[str] = None
    last_disconnected: Optional[str] = None
    disconnect_reason: Optional[DisconnectReason] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    reconnect_attempts: int = 0
    latency_ms: Optional[float] = None
    last_health_check: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['status'] = self.status.value if self.status else None
        d['disconnect_reason'] = self.disconnect_reason.value if self.disconnect_reason else None
        return d

class ConnectionMonitor:
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
        
        self._connections: Dict[str, ConnectionState] = {}
        self._event_history: List[Dict[str, Any]] = []
        self._max_history = 1000
        self._alert_callbacks: List[Callable] = []
        self._state_change_callbacks: List[Callable] = []
        self._reconnect_policies: Dict[str, Dict] = {}
        self._lock = threading.Lock()
        
        self._default_reconnect_policy = {
            'max_attempts': 10,
            'base_delay': 5,
            'max_delay': 300,
            'backoff_multiplier': 2
        }
        
        self._register_default_services()
        self._initialized = True
        print("[CONNECTION MONITOR] ✓ Initialized")
    
    def _register_default_services(self):
        default_services = [
            ("discord", "messaging"),
            ("telegram", "messaging"),
            ("webull", "broker"),
            ("alpaca_paper", "broker"),
            ("alpaca_live", "broker"),
            ("tastytrade", "broker"),
            ("ibkr", "broker"),
            ("robinhood", "broker"),
            ("schwab", "broker"),
        ]
        for name, stype in default_services:
            self._connections[name] = ConnectionState(
                service_name=name,
                service_type=stype,
                status=ConnectionStatus.NOT_CONFIGURED
            )
    
    def register_service(self, name: str, service_type: str, 
                        reconnect_policy: Optional[Dict] = None):
        with self._lock:
            self._connections[name] = ConnectionState(
                service_name=name,
                service_type=service_type,
                status=ConnectionStatus.NOT_CONFIGURED
            )
            if reconnect_policy:
                self._reconnect_policies[name] = reconnect_policy
    
    def set_connected(self, service_name: str, latency_ms: Optional[float] = None,
                     metadata: Optional[Dict] = None):
        with self._lock:
            if service_name not in self._connections:
                return
            
            state = self._connections[service_name]
            was_disconnected = state.status != ConnectionStatus.CONNECTED
            
            now = datetime.utcnow().isoformat()
            state.status = ConnectionStatus.CONNECTED
            state.last_connected = now
            state.last_health_check = now
            state.disconnect_reason = None
            state.error_message = None
            state.error_code = None
            state.reconnect_attempts = 0
            if latency_ms is not None:
                state.latency_ms = latency_ms
            if metadata:
                state.metadata.update(metadata)
            
            if was_disconnected:
                self._add_event(service_name, "connected", 
                              f"{service_name} connected successfully")
                self._notify_state_change(state)
                print(f"[CONNECTION MONITOR] ✓ {service_name} CONNECTED")
    
    def set_disconnected(self, service_name: str, 
                        reason: DisconnectReason = DisconnectReason.UNKNOWN,
                        error_message: Optional[str] = None,
                        error_code: Optional[str] = None):
        with self._lock:
            if service_name not in self._connections:
                return
            
            state = self._connections[service_name]
            was_connected = state.status == ConnectionStatus.CONNECTED
            
            now = datetime.utcnow().isoformat()
            state.status = ConnectionStatus.DISCONNECTED
            state.last_disconnected = now
            state.disconnect_reason = reason
            state.error_message = error_message
            state.error_code = error_code
            
            if was_connected:
                self._add_event(service_name, "disconnected",
                              f"{service_name} disconnected: {reason.value}",
                              {"reason": reason.value, "error": error_message, "code": error_code})
                self._trigger_alert(state)
                self._notify_state_change(state)
                print(f"[CONNECTION MONITOR] ⚠️ {service_name} DISCONNECTED: {reason.value} - {error_message}")
    
    def set_reconnecting(self, service_name: str, attempt: int = 1):
        with self._lock:
            if service_name not in self._connections:
                return
            
            state = self._connections[service_name]
            state.status = ConnectionStatus.RECONNECTING
            state.reconnect_attempts = attempt
            
            self._add_event(service_name, "reconnecting",
                          f"{service_name} reconnecting (attempt {attempt})")
            self._notify_state_change(state)
            print(f"[CONNECTION MONITOR] 🔄 {service_name} RECONNECTING (attempt {attempt})")
    
    def set_error(self, service_name: str, error_message: str,
                 error_code: Optional[str] = None):
        with self._lock:
            if service_name not in self._connections:
                return
            
            state = self._connections[service_name]
            state.status = ConnectionStatus.ERROR
            state.error_message = error_message
            state.error_code = error_code
            
            self._add_event(service_name, "error",
                          f"{service_name} error: {error_message}",
                          {"error": error_message, "code": error_code})
            self._trigger_alert(state)
            self._notify_state_change(state)
            print(f"[CONNECTION MONITOR] ❌ {service_name} ERROR: {error_message}")
    
    def update_health_check(self, service_name: str, latency_ms: Optional[float] = None):
        with self._lock:
            if service_name not in self._connections:
                return
            state = self._connections[service_name]
            state.last_health_check = datetime.utcnow().isoformat()
            if latency_ms is not None:
                state.latency_ms = latency_ms
    
    def get_all_status(self) -> Dict[str, Dict]:
        with self._lock:
            return {name: state.to_dict() for name, state in self._connections.items()}
    
    def get_service_status(self, service_name: str) -> Optional[Dict]:
        with self._lock:
            if service_name in self._connections:
                return self._connections[service_name].to_dict()
            return None
    
    def get_active_services(self) -> Dict[str, Dict]:
        with self._lock:
            return {
                name: state.to_dict() 
                for name, state in self._connections.items()
                if state.status != ConnectionStatus.NOT_CONFIGURED
            }
    
    def get_disconnected_services(self) -> List[Dict]:
        with self._lock:
            return [
                state.to_dict() 
                for state in self._connections.values()
                if state.status in (ConnectionStatus.DISCONNECTED, ConnectionStatus.ERROR)
            ]
    
    def get_event_history(self, limit: int = 100, 
                         service_name: Optional[str] = None) -> List[Dict]:
        with self._lock:
            events = self._event_history.copy()
            if service_name:
                events = [e for e in events if e.get('service') == service_name]
            return events[-limit:]
    
    def register_alert_callback(self, callback: Callable):
        with self._lock:
            self._alert_callbacks.append(callback)
    
    def register_state_change_callback(self, callback: Callable):
        with self._lock:
            self._state_change_callbacks.append(callback)
    
    def _add_event(self, service: str, event_type: str, message: str,
                  details: Optional[Dict] = None):
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "service": service,
            "event_type": event_type,
            "message": message,
            "details": details or {}
        }
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]
    
    def _trigger_alert(self, state: ConnectionState):
        for callback in self._alert_callbacks:
            try:
                callback(state.to_dict())
            except Exception as e:
                print(f"[CONNECTION MONITOR] Alert callback error: {e}")
    
    def _notify_state_change(self, state: ConnectionState):
        for callback in self._state_change_callbacks:
            try:
                callback(state.to_dict())
            except Exception as e:
                print(f"[CONNECTION MONITOR] State change callback error: {e}")
    
    def get_reconnect_delay(self, service_name: str) -> float:
        policy = self._reconnect_policies.get(service_name, self._default_reconnect_policy)
        state = self._connections.get(service_name)
        if not state:
            return policy['base_delay']
        
        delay = policy['base_delay'] * (policy['backoff_multiplier'] ** state.reconnect_attempts)
        return min(delay, policy['max_delay'])
    
    def should_reconnect(self, service_name: str) -> bool:
        policy = self._reconnect_policies.get(service_name, self._default_reconnect_policy)
        state = self._connections.get(service_name)
        if not state:
            return True
        return state.reconnect_attempts < policy['max_attempts']

def classify_discord_error(error_code: Optional[int] = None, 
                          error_message: Optional[str] = None) -> DisconnectReason:
    if error_code:
        error_map = {
            4004: DisconnectReason.TOKEN_INVALID,
            4014: DisconnectReason.TOKEN_INVALID,
            4001: DisconnectReason.UNKNOWN,
            4003: DisconnectReason.TOKEN_EXPIRED,
            4005: DisconnectReason.AUTH_FAILED,
            4007: DisconnectReason.SESSION_EXPIRED,
            4008: DisconnectReason.RATE_LIMITED,
            4009: DisconnectReason.SESSION_EXPIRED,
            4010: DisconnectReason.TOKEN_INVALID,
            4011: DisconnectReason.UNKNOWN,
            4012: DisconnectReason.UNKNOWN,
            4013: DisconnectReason.TOKEN_INVALID,
        }
        return error_map.get(error_code, DisconnectReason.WEBSOCKET_CLOSED)
    
    if error_message:
        msg_lower = error_message.lower()
        if 'token' in msg_lower and ('invalid' in msg_lower or 'expired' in msg_lower):
            return DisconnectReason.TOKEN_INVALID
        if 'rate' in msg_lower and 'limit' in msg_lower:
            return DisconnectReason.RATE_LIMITED
        if 'timeout' in msg_lower:
            return DisconnectReason.NETWORK_TIMEOUT
        if 'auth' in msg_lower:
            return DisconnectReason.AUTH_FAILED
    
    return DisconnectReason.UNKNOWN

def classify_broker_error(broker: str, error_code: Optional[str] = None,
                         error_message: Optional[str] = None,
                         http_status: Optional[int] = None) -> DisconnectReason:
    if http_status:
        if http_status == 401:
            return DisconnectReason.AUTH_FAILED
        if http_status == 403:
            return DisconnectReason.CREDENTIAL_REVOKED
        if http_status == 429:
            return DisconnectReason.RATE_LIMITED
        if http_status >= 500:
            return DisconnectReason.API_ERROR
    
    if error_message:
        msg_lower = error_message.lower()
        if 'token' in msg_lower and ('expired' in msg_lower or 'invalid' in msg_lower):
            return DisconnectReason.TOKEN_EXPIRED
        if 'refresh' in msg_lower and 'fail' in msg_lower:
            return DisconnectReason.SESSION_EXPIRED
        if 'timeout' in msg_lower:
            return DisconnectReason.NETWORK_TIMEOUT
        if 'rate' in msg_lower or 'throttl' in msg_lower:
            return DisconnectReason.RATE_LIMITED
        if 'auth' in msg_lower or 'credential' in msg_lower or 'login' in msg_lower:
            return DisconnectReason.AUTH_FAILED
        if 'maintenance' in msg_lower:
            return DisconnectReason.MAINTENANCE
    
    return DisconnectReason.UNKNOWN

_monitor: Optional[ConnectionMonitor] = None

def get_connection_monitor() -> ConnectionMonitor:
    global _monitor
    if _monitor is None:
        _monitor = ConnectionMonitor()
    return _monitor
