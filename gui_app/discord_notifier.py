"""
Discord Trade Notification System
Sends BTO/STC messages to Discord via webhook

NOTE: This module is DEPRECATED when Trade Monitor is enabled.
Trade Monitor provides a more robust signal posting system with @everyone support.
"""
import requests
import logging
from datetime import datetime
from typing import Optional, Dict, Set
from .config_service import get_discord_notifications

logger = logging.getLogger(__name__)

# Track last alert time per broker to avoid spam (cooldown in seconds)
_last_alert_time: Dict[str, datetime] = {}
_alert_cooldown_seconds = 300  # 5 minute cooldown between same alerts
_alerted_brokers: Set[str] = set()  # Track which brokers have been alerted as disconnected


def send_system_alert(
    alert_type: str,
    message: str,
    severity: str = "warning",  # "info", "warning", "error", "critical"
    broker_name: Optional[str] = None
):
    """
    Send system alert notification to Discord
    
    Args:
        alert_type: Type of alert (broker_disconnect, broker_reconnect, error, etc.)
        message: Alert message
        severity: Alert severity level
        broker_name: Optional broker name for broker-specific alerts
    
    Returns:
        bool: True if notification was sent, False otherwise
    """
    global _last_alert_time, _alerted_brokers
    
    try:
        # Get notification settings
        settings = get_discord_notifications()
        
        if not settings.get('enabled', True):
            logger.info("Discord notifications disabled - skipping system alert")
            return False
        
        # Check for system alerts webhook (prefer dedicated webhook, fall back to main)
        webhook_url = settings.get('system_webhook_url') or settings.get('webhook_url', '')
        if not webhook_url:
            logger.warning("Discord webhook URL not configured - cannot send system alert")
            return False
        
        # Apply cooldown to prevent spam
        alert_key = f"{alert_type}:{broker_name}" if broker_name else alert_type
        now = datetime.now()
        
        if alert_key in _last_alert_time:
            elapsed = (now - _last_alert_time[alert_key]).total_seconds()
            if elapsed < _alert_cooldown_seconds:
                logger.debug(f"Alert cooldown active for {alert_key} ({elapsed:.0f}s < {_alert_cooldown_seconds}s)")
                return False
        
        # Update last alert time
        _last_alert_time[alert_key] = now
        
        # Severity emoji mapping
        severity_emoji = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "critical": "🚨"
        }
        
        emoji = severity_emoji.get(severity, "📢")
        
        # Format the message
        formatted_message = f"{emoji} **[SYSTEM ALERT]** {message}"
        
        if broker_name:
            formatted_message = f"{emoji} **[{broker_name.upper()}]** {message}"
        
        # Send notification
        payload = {
            "content": formatted_message,
            "username": "BotifyTrades System"
        }
        
        response = requests.post(webhook_url, json=payload, timeout=5)
        
        if response.status_code == 204:
            logger.info(f"System alert sent: {message}")
            return True
        else:
            logger.error(f"Discord system alert failed: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Failed to send system alert: {e}")
        return False


def notify_broker_disconnected(broker_name: str, error_message: Optional[str] = None):
    """
    Notify when a broker connection is lost
    Only sends one alert per broker until it reconnects
    """
    global _alerted_brokers
    
    # Only alert once per broker until reconnection
    if broker_name in _alerted_brokers:
        return False
    
    _alerted_brokers.add(broker_name)
    
    message = f"Connection lost to {broker_name}"
    if error_message:
        message += f": {error_message}"
    message += ". Trading for this broker is paused until reconnection."
    
    return send_system_alert(
        alert_type="broker_disconnect",
        message=message,
        severity="error",
        broker_name=broker_name
    )


def notify_broker_reconnected(broker_name: str):
    """
    Notify when a broker connection is restored
    """
    global _alerted_brokers
    
    # Only send reconnection notice if we previously alerted about disconnection
    if broker_name not in _alerted_brokers:
        return False
    
    _alerted_brokers.discard(broker_name)
    
    return send_system_alert(
        alert_type="broker_reconnect",
        message=f"Connection restored to {broker_name}. Trading resumed.",
        severity="info",
        broker_name=broker_name
    )


def is_broker_alerted(broker_name: str) -> bool:
    """Check if a broker has been alerted as disconnected"""
    return broker_name in _alerted_brokers


def clear_broker_alert(broker_name: str):
    """Clear the alert status for a broker without sending notification"""
    _alerted_brokers.discard(broker_name)


def _is_trade_monitor_enabled() -> bool:
    """Check if Trade Monitor is enabled (should take precedence over this notifier)"""
    try:
        from gui_app.database import get_trade_monitor_settings
        settings = get_trade_monitor_settings()
        return settings.get('enabled', False)
    except Exception:
        return False


def send_trade_notification(
    symbol: str,
    action: str,  # "BTO" or "STC"
    quantity: int,
    price: float,
    expiry: Optional[str] = None,
    strike: Optional[float] = None,
    call_put: Optional[str] = None,
    pnl: Optional[float] = None,
    pnl_percent: Optional[float] = None
):
    """
    Send trade notification to Discord in bot-readable format
    
    Format:
    - BTO: "BTO 1 A 130p 12/19 @ 1.15"
    - STC: "STC 3 BABA 170c 11/28 @ 2.67"
    
    NOTE: This function is skipped when Trade Monitor is enabled to prevent duplicates.
    """
    try:
        # Skip if Trade Monitor is enabled (it handles signal posting)
        if _is_trade_monitor_enabled():
            logger.info("Discord notifier skipped - Trade Monitor is enabled")
            return
        
        # Get notification settings
        settings = get_discord_notifications()
        
        if not settings.get('enabled', True):
            logger.info("Discord notifications disabled")
            return
        
        webhook_url = settings.get('webhook_url', '')
        if not webhook_url:
            logger.warning("Discord webhook URL not configured")
            return
        
        # Build message in bot-readable format: "BTO 1 A 130p 12/19 @ 1.15"
        message = f"{action} {quantity} {symbol}"
        
        # Add option details if available
        if expiry and strike and call_put:
            # Convert date format: "2025-11-28" → "11/28"
            expiry_formatted = expiry
            if '-' in expiry:  # Format: YYYY-MM-DD
                parts = expiry.split('-')
                if len(parts) == 3:
                    expiry_formatted = f"{parts[1]}/{parts[2]}"  # MM/DD
            
            # Format: 130p for puts, 170c for calls
            option_type = call_put.lower()[0]  # 'c' or 'p'
            message += f" {int(strike)}{option_type} {expiry_formatted}"
        
        # Add price
        message += f" @ {price:.2f}"
        
        # Send as plain text content (bot-readable format)
        payload = {
            "content": message,
            "username": "BotifyTrades"
        }
        
        response = requests.post(webhook_url, json=payload, timeout=5)
        
        if response.status_code == 204:
            logger.info(f"Discord notification sent: {message}")
        else:
            logger.error(f"Discord webhook failed: {response.status_code} - {response.text}")
            
    except Exception as e:
        logger.error(f"Failed to send Discord notification: {e}")


def send_bto_notification(symbol: str, quantity: int, price: float, **kwargs):
    """Convenience function for BTO notifications"""
    send_trade_notification(
        symbol=symbol,
        action="BTO",
        quantity=quantity,
        price=price,
        **kwargs
    )


def send_stc_notification(symbol: str, quantity: int, price: float, entry_price: float, **kwargs):
    """Convenience function for STC notifications with P&L calculation"""
    # Calculate P&L only if entry_price is available
    pnl = None
    pnl_percent = None
    
    if entry_price and entry_price > 0:
        is_option = 'strike' in kwargs and kwargs['strike'] is not None
        multiplier = 100 if is_option else 1
        
        pnl = (price - entry_price) * quantity * multiplier
        pnl_percent = ((price - entry_price) / entry_price) * 100
    
    send_trade_notification(
        symbol=symbol,
        action="STC",
        quantity=quantity,
        price=price,
        pnl=pnl,
        pnl_percent=pnl_percent,
        **kwargs
    )


def send_cancel_notification(symbol: str, quantity: int, price: float, is_option: bool = False, order_id: str = "", **kwargs):
    """Send notification when an order is canceled in bot-readable format"""
    try:
        # Get notification settings
        settings = get_discord_notifications()
        
        if not settings.get('enabled', True):
            logger.info("Discord notifications disabled")
            return
        
        webhook_url = settings.get('webhook_url', '')
        if not webhook_url:
            logger.warning("Discord webhook URL not configured")
            return
        
        # Build message in bot-readable format: "CANCELED 1 A 130p 12/19 @ 1.15"
        message = f"CANCELED {quantity} {symbol}"
        
        # Add option details if available
        if is_option and 'expiry' in kwargs and 'strike' in kwargs and 'call_put' in kwargs:
            # Convert date format: "2025-11-28" → "11/28"
            expiry = kwargs['expiry']
            expiry_formatted = expiry
            if '-' in expiry:  # Format: YYYY-MM-DD
                parts = expiry.split('-')
                if len(parts) == 3:
                    expiry_formatted = f"{parts[1]}/{parts[2]}"  # MM/DD
            
            option_type = kwargs['call_put'].lower()[0]  # 'c' or 'p'
            message += f" {int(kwargs['strike'])}{option_type} {expiry_formatted}"
        
        # Add price
        message += f" @ {price:.2f}"
        
        # Send as plain text content (bot-readable format)
        payload = {
            "content": message,
            "username": "BotifyTrades"
        }
        
        response = requests.post(webhook_url, json=payload, timeout=5)
        
        if response.status_code == 204:
            logger.info(f"Discord cancel notification sent: {message}")
        else:
            logger.error(f"Discord webhook failed: {response.status_code} - {response.text}")
            
    except Exception as e:
        logger.error(f"Failed to send Discord cancel notification: {e}")
