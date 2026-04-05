"""
Broker Health Monitor
Tracks broker connection status and sends notifications when connections are lost or restored
"""
import logging
from datetime import datetime
from typing import Dict, Optional, Set
from threading import Lock

logger = logging.getLogger(__name__)

_broker_status: Dict[str, bool] = {}
_last_check_time: Dict[str, datetime] = {}
_status_lock = Lock()
_consecutive_failures: Dict[str, int] = {}
_FAILURE_THRESHOLD = 3


def check_broker_health(broker_name: str, is_connected: bool, error_message: Optional[str] = None):
    """
    Check and update broker health status
    Sends notifications when status changes
    
    Args:
        broker_name: Name of the broker
        is_connected: True if broker is connected and working
        error_message: Optional error message if disconnected
    """
    with _status_lock:
        previous_status = _broker_status.get(broker_name)
        current_failures = _consecutive_failures.get(broker_name, 0)
        
        if is_connected:
            _consecutive_failures[broker_name] = 0
            
            if previous_status is False:
                _broker_status[broker_name] = True
                _last_check_time[broker_name] = datetime.now()
                logger.info(f"[HEALTH] {broker_name} connection restored")
                
                try:
                    from gui_app.discord_notifier import notify_broker_reconnected
                    notify_broker_reconnected(broker_name)
                except Exception as e:
                    logger.error(f"[HEALTH] Failed to send reconnection notification: {e}")
        else:
            _consecutive_failures[broker_name] = current_failures + 1
            
            if _consecutive_failures[broker_name] >= _FAILURE_THRESHOLD:
                if previous_status is not False:
                    _broker_status[broker_name] = False
                    _last_check_time[broker_name] = datetime.now()
                    logger.warning(f"[HEALTH] {broker_name} connection lost after {_FAILURE_THRESHOLD} consecutive failures")
                    
                    try:
                        from gui_app.discord_notifier import notify_broker_disconnected
                        notify_broker_disconnected(broker_name, error_message)
                    except Exception as e:
                        logger.error(f"[HEALTH] Failed to send disconnection notification: {e}")


def get_broker_status(broker_name: str) -> Optional[bool]:
    """Get the current connection status of a broker"""
    with _status_lock:
        return _broker_status.get(broker_name)


def get_all_broker_statuses() -> Dict[str, bool]:
    """Get all broker statuses"""
    with _status_lock:
        return dict(_broker_status)


def is_broker_healthy(broker_name: str) -> bool:
    """Check if a broker is currently healthy"""
    with _status_lock:
        return _broker_status.get(broker_name, True)


def reset_broker_status(broker_name: str):
    """Reset the status tracking for a broker"""
    with _status_lock:
        _broker_status.pop(broker_name, None)
        _last_check_time.pop(broker_name, None)
        _consecutive_failures.pop(broker_name, None)
