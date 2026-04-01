"""
Discord Trade Notification System
Sends BTO/STC messages to Discord via webhook

NOTE: This module is DEPRECATED when Trade Monitor is enabled.
Trade Monitor provides a more robust signal posting system with @everyone support.
"""
import requests
import logging
import threading
import time as _time_mod
from datetime import datetime
from typing import Optional, Dict, Set
from .config_service import get_discord_notifications

logger = logging.getLogger(__name__)

_notifier_lock = threading.Lock()

_last_alert_time: Dict[str, datetime] = {}
_alert_cooldown_seconds = 300
_alerted_brokers: Set[str] = set()


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
    try:
        settings = get_discord_notifications()
        
        if not settings.get('enabled', True):
            logger.info("Discord notifications disabled - skipping system alert")
            return False
        
        webhook_url = settings.get('system_webhook_url') or settings.get('webhook_url', '')
        if not webhook_url:
            logger.warning("Discord webhook URL not configured - cannot send system alert")
            return False
        
        alert_key = f"{alert_type}:{broker_name}" if broker_name else alert_type
        now = datetime.now()
        
        with _notifier_lock:
            if alert_key in _last_alert_time:
                elapsed = (now - _last_alert_time[alert_key]).total_seconds()
                if elapsed < _alert_cooldown_seconds:
                    logger.debug(f"Alert cooldown active for {alert_key} ({elapsed:.0f}s < {_alert_cooldown_seconds}s)")
                    return False
            _last_alert_time[alert_key] = now
        
        severity_emoji = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "critical": "🚨"
        }
        
        emoji = severity_emoji.get(severity, "📢")
        
        formatted_message = f"{emoji} **[SYSTEM ALERT]** {message}"
        if broker_name:
            formatted_message = f"{emoji} **[{broker_name.upper()}]** {message}"
        
        payload = {
            "content": formatted_message,
            "username": "BotifyTrades System"
        }
        
        return _send_webhook_with_retry(webhook_url, payload)
            
    except Exception as e:
        logger.error(f"Failed to send system alert: {e}")
        return False


def _send_webhook_with_retry(webhook_url: str, payload: dict, max_retries: int = 2) -> bool:
    """Send webhook with Discord 429 rate-limit retry handling."""
    for attempt in range(max_retries + 1):
        try:
            response = requests.post(webhook_url, json=payload, timeout=5)
            
            if response.status_code == 204:
                logger.info(f"Webhook sent successfully (attempt {attempt + 1})")
                return True
            elif response.status_code == 429:
                retry_after = 1.0
                try:
                    retry_after = float(response.headers.get('Retry-After', 1.0))
                    retry_data = response.json()
                    retry_after = max(retry_after, retry_data.get('retry_after', 1.0))
                except Exception:
                    pass
                retry_after = min(retry_after, 5.0)
                logger.warning(f"Discord rate limited (429), retry after {retry_after}s (attempt {attempt + 1}/{max_retries + 1})")
                if attempt < max_retries:
                    _time_mod.sleep(retry_after)
                    continue
                else:
                    logger.error(f"Discord rate limit exhausted after {max_retries + 1} attempts")
                    return False
            else:
                logger.error(f"Discord webhook failed: {response.status_code} - {response.text}")
                return False
        except requests.exceptions.Timeout:
            logger.warning(f"Webhook timeout (attempt {attempt + 1}/{max_retries + 1})")
            if attempt < max_retries:
                _time_mod.sleep(0.5)
                continue
        except Exception as e:
            logger.error(f"Webhook send error: {e}")
            return False
    return False


def notify_broker_disconnected(broker_name: str, error_message: Optional[str] = None):
    """
    Notify when a broker connection is lost
    Only sends one alert per broker until it reconnects
    """
    with _notifier_lock:
        if broker_name in _alerted_brokers:
            return False
        _alerted_brokers.add(broker_name)
    
    broker_label = broker_name.upper()
    
    message = f"Connection lost to **{broker_label}**"
    if error_message:
        message += f": {error_message}"
    message += ". Trading for this broker is paused until reconnection."
    
    send_critical_alert(
        alert_type="broker_disconnect",
        title=f"[{broker_label}] DISCONNECTED",
        message=message,
        broker=broker_name
    )
    
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
    with _notifier_lock:
        if broker_name not in _alerted_brokers:
            return False
        _alerted_brokers.discard(broker_name)
    broker_label = broker_name.upper()
    
    send_critical_alert(
        alert_type="broker_reconnect",
        title=f"[{broker_label}] RECONNECTED",
        message=f"Connection restored to **{broker_label}**. Trading resumed.",
        broker=broker_name
    )
    
    return send_system_alert(
        alert_type="broker_reconnect",
        message=f"Connection restored to **{broker_label}**. Trading resumed.",
        severity="info",
        broker_name=broker_name
    )


def is_broker_alerted(broker_name: str) -> bool:
    """Check if a broker has been alerted as disconnected"""
    with _notifier_lock:
        return broker_name in _alerted_brokers


def clear_broker_alert(broker_name: str):
    """Clear the alert status for a broker without sending notification"""
    with _notifier_lock:
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
        
        _send_webhook_with_retry(webhook_url, payload)
            
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
        
        _send_webhook_with_retry(webhook_url, payload)
            
    except Exception as e:
        logger.error(f"Failed to send Discord cancel notification: {e}")


# ============================================================================
# CRITICAL ALERTS - High Priority Notifications
# ============================================================================

_notification_history: list = []
_max_history = 100
_recent_dedup: dict = {}
_dedup_ttl = 300
_symbol_dedup: dict = {}
_symbol_dedup_ttl = 300
_history_lock = threading.Lock()
import uuid as _uuid_mod

def get_notification_history() -> list:
    """Get recent notification history for browser display"""
    with _history_lock:
        return list(_notification_history)

def clear_notification_history():
    """Clear notification history"""
    global _notification_history, _recent_dedup, _symbol_dedup
    with _history_lock:
        _notification_history = []
        _recent_dedup = {}
        _symbol_dedup = {}

def _add_to_history(notification: dict):
    """Add notification to history for browser retrieval with deduplication"""
    global _notification_history
    
    if 'id' not in notification:
        notification['id'] = str(_uuid_mod.uuid4())[:12]
    
    dedup_key = f"{notification.get('type', '')}:{notification.get('title', '')}:{notification.get('message', '')}"
    now = _time_mod.time()
    
    with _history_lock:
        expired = [k for k, t in _recent_dedup.items() if now - t > _dedup_ttl]
        for k in expired:
            del _recent_dedup[k]
        
        if dedup_key in _recent_dedup:
            return
        _recent_dedup[dedup_key] = now
        
        symbol = notification.get('symbol', '')
        ntype = notification.get('type', '')
        broker = notification.get('broker', '')
        if symbol and ntype in ('order_filled_bto', 'order_failed'):
            sym_key = f"{symbol}:{ntype}:{broker}"
            sym_expired = [k for k, t in _symbol_dedup.items() if now - t > _symbol_dedup_ttl]
            for k in sym_expired:
                del _symbol_dedup[k]
            if sym_key in _symbol_dedup:
                return
            _symbol_dedup[sym_key] = now
        
        _notification_history.insert(0, notification)
        if len(_notification_history) > _max_history:
            _notification_history = _notification_history[:_max_history]
    
    _persist_notification_to_db(notification)


_notification_table_initialized = False

def _ensure_notification_table():
    """Create notification_log table if needed (runs once)."""
    global _notification_table_initialized
    if _notification_table_initialized:
        return
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notification_log (
                id TEXT PRIMARY KEY,
                type TEXT,
                title TEXT,
                message TEXT,
                symbol TEXT,
                broker TEXT,
                timestamp TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                read INTEGER DEFAULT 0
            )
        """)
        conn.commit()
        _notification_table_initialized = True
    except Exception as e:
        logger.debug(f"Failed to create notification_log table: {e}")


def _persist_notification_to_db(notification: dict):
    """Persist notification to SQLite for crash recovery."""
    try:
        _ensure_notification_table()
        from gui_app.database import get_connection
        conn = get_connection()
        conn.execute(
            """INSERT OR IGNORE INTO notification_log (id, type, title, message, symbol, broker, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                notification.get('id', ''),
                notification.get('type', ''),
                notification.get('title', ''),
                notification.get('message', ''),
                notification.get('symbol', ''),
                notification.get('broker', ''),
                notification.get('timestamp', '')
            )
        )
        conn.commit()
        
        conn.execute("DELETE FROM notification_log WHERE created_at < datetime('now', '-24 hours')")
        conn.commit()
    except Exception as e:
        logger.debug(f"Failed to persist notification to DB: {e}")


def load_notifications_from_db() -> list:
    """Load unread notifications from DB on startup for crash recovery."""
    try:
        _ensure_notification_table()
        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.execute(
            "SELECT * FROM notification_log WHERE read = 0 ORDER BY created_at DESC LIMIT 50"
        )
        rows = cursor.fetchall()
        notifications = []
        for row in rows:
            notifications.append({
                'id': row[0],
                'type': row[1],
                'title': row[2],
                'message': row[3],
                'symbol': row[4],
                'broker': row[5],
                'timestamp': row[6]
            })
        
        with _history_lock:
            global _notification_history
            existing_ids = {n.get('id') for n in _notification_history}
            for n in notifications:
                if n['id'] not in existing_ids:
                    _notification_history.append(n)
            _notification_history.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            _notification_history = _notification_history[:_max_history]
        
        return notifications
    except Exception as e:
        logger.debug(f"Failed to load notifications from DB: {e}")
        return []


def send_critical_alert(
    alert_type: str,
    title: str,
    message: str,
    symbol: Optional[str] = None,
    broker: Optional[str] = None,
    details: Optional[Dict] = None
) -> bool:
    """
    Send critical alert for order failures, stop loss triggers, etc.
    
    Args:
        alert_type: Type of alert (order_failed, stop_loss_triggered, order_filled, etc.)
        title: Short title for the notification
        message: Detailed message
        symbol: Trading symbol involved
        broker: Broker name
        details: Additional details dict
    
    Returns:
        bool: True if notification was sent successfully
    """
    try:
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        notification = {
            "type": alert_type,
            "title": title,
            "message": message,
            "symbol": symbol,
            "broker": broker,
            "details": details or {},
            "timestamp": timestamp,
            "datetime": datetime.now().isoformat()
        }
        
        _add_to_history(notification)
        
        settings = get_discord_notifications()
        
        if not settings.get('enabled', True):
            logger.info("Discord notifications disabled - alert stored locally only")
            return True
        
        webhook_url = settings.get('webhook_url', '')
        if not webhook_url:
            logger.info("Discord webhook not configured - alert stored locally only")
            return True
        
        severity_config = {
            "order_failed": {"emoji": "🚨", "color": 15158332, "mention": True},
            "stop_loss_triggered": {"emoji": "🛑", "color": 15158332, "mention": True},
            "stop_loss_failed": {"emoji": "💥", "color": 15158332, "mention": True},
            "order_placed_bto": {"emoji": "📤", "color": 16761600, "mention": False},
            "order_placed_stc": {"emoji": "📤", "color": 16761600, "mention": False},
            "conditional_created": {"emoji": "📋", "color": 5793266, "mention": False},
            "conditional_triggered": {"emoji": "⚡", "color": 16776960, "mention": False},
            "conditional_expired": {"emoji": "⏰", "color": 10070709, "mention": False},
            "conditional_failed": {"emoji": "❌", "color": 15158332, "mention": True},
            "conditional_cancelled": {"emoji": "🚫", "color": 10070709, "mention": False},
            "order_filled_bto": {"emoji": "🟢", "color": 3066993, "mention": False},
            "order_filled_stc": {"emoji": "🔴", "color": 15844367, "mention": False},
            "profit_target_hit": {"emoji": "🎯", "color": 3066993, "mention": False},
            "trailing_stop_triggered": {"emoji": "📉", "color": 15844367, "mention": False},
            "trailing_stop": {"emoji": "📉", "color": 15844367, "mention": False},
            "giveback_guard": {"emoji": "🛡️", "color": 16761600, "mention": True},
            "broker_disconnect": {"emoji": "🔌", "color": 15158332, "mention": True},
            "broker_reconnect": {"emoji": "✅", "color": 3066993, "mention": False},
        }
        
        config = severity_config.get(alert_type, {"emoji": "📢", "color": 7506394, "mention": False})
        
        embed = {
            "title": f"{config['emoji']} {title}",
            "description": message,
            "color": config['color'],
            "timestamp": datetime.now().isoformat(),
            "footer": {"text": "BotifyTrades Alert System"}
        }
        
        fields = []
        if symbol:
            fields.append({"name": "Symbol", "value": symbol, "inline": True})
        if broker:
            fields.append({"name": "Broker", "value": broker, "inline": True})
        if details:
            for key, value in details.items():
                if key not in ['symbol', 'broker']:
                    fields.append({"name": key.replace('_', ' ').title(), "value": str(value), "inline": True})
        
        if fields:
            embed['fields'] = fields
        
        content = "@everyone" if config['mention'] else None
        
        payload = {
            "embeds": [embed],
            "username": "BotifyTrades Alerts"
        }
        if content:
            payload["content"] = content
        
        return _send_webhook_with_retry(webhook_url, payload)
            
    except Exception as e:
        logger.error(f"Failed to send critical alert: {e}")
        return False


def notify_order_failed(
    symbol: str,
    action: str,
    broker: str,
    error_message: str,
    quantity: Optional[int] = None,
    price: Optional[float] = None,
    is_risk_order: bool = False
):
    """Notify when an order fails to execute"""
    broker_label = broker.upper() if broker else 'Unknown'
    title = f"[{broker_label}] ORDER FAILED: {action} {symbol}"
    
    if is_risk_order:
        title = f"[{broker_label}] RISK ORDER FAILED: {action} {symbol}"
        message = f"**CRITICAL**: Risk management order failed on **{broker_label}**!\n\n{error_message}\n\nManual intervention may be required."
    else:
        message = f"**{broker_label}** order execution failed: {error_message}"
    
    details = {}
    if quantity:
        details['Quantity'] = quantity
    if price:
        details['Price'] = f"${price:.2f}"
    details['Error'] = error_message[:100]
    
    return send_critical_alert(
        alert_type="order_failed",
        title=title,
        message=message,
        symbol=symbol,
        broker=broker,
        details=details
    )


def notify_stop_loss_triggered(
    symbol: str,
    broker: str,
    entry_price: float,
    exit_price: float,
    loss_percent: float,
    quantity: int,
    channel: Optional[str] = None
):
    """Notify when a stop loss is triggered"""
    pnl = (exit_price - entry_price) * quantity * 100
    broker_label = broker.upper() if broker else 'Unknown'
    
    title = f"[{broker_label}] STOP LOSS: {symbol}"
    message = f"**{broker_label}** stop loss triggered at **{loss_percent:.1f}%** loss"
    
    details = {
        'Entry': f"${entry_price:.2f}",
        'Exit': f"${exit_price:.2f}",
        'Loss': f"{loss_percent:.1f}%",
        'Qty': quantity,
        'P&L': f"${pnl:.2f}"
    }
    if channel:
        details['Channel'] = channel
    
    return send_critical_alert(
        alert_type="stop_loss_triggered",
        title=title,
        message=message,
        symbol=symbol,
        broker=broker,
        details=details
    )


def notify_order_placed(
    symbol: str,
    action: str,
    broker: str,
    quantity: int,
    price: float,
    order_id: Optional[str] = None,
    strike: Optional[float] = None,
    expiry: Optional[str] = None,
    opt_type: Optional[str] = None
):
    """Notify when an order is submitted/placed (not yet filled)."""
    alert_type = "order_placed_bto" if action.upper() == "BTO" else "order_placed_stc"
    broker_label = broker.upper() if broker else 'Unknown'
    
    is_option = bool(strike and expiry and opt_type)
    unit_label = "contracts" if is_option else "shares"
    
    option_str = ""
    if is_option:
        option_str = f" ${strike}{opt_type} {expiry}"
    
    title = f"[{broker_label}] {action.upper()} ORDER PLACED: {symbol}{option_str}"
    price_str = f"${price:.2f}" if price is not None else "MARKET"
    message = f"**{broker_label}**: {quantity} {unit_label} @ {price_str}"
    
    details = {
        'Qty': quantity,
        'Price': price_str,
        'Status': 'PENDING'
    }
    if order_id:
        details['Order ID'] = str(order_id)[:12]
    
    return send_critical_alert(
        alert_type=alert_type,
        title=title,
        message=message,
        symbol=symbol,
        broker=broker,
        details=details
    )


def notify_order_filled(
    symbol: str,
    action: str,
    broker: str,
    quantity: int,
    price: float,
    strike: Optional[float] = None,
    expiry: Optional[str] = None,
    opt_type: Optional[str] = None,
    pnl: Optional[float] = None,
    pnl_percent: Optional[float] = None
):
    """Notify when an order is actually filled (confirmed by broker)."""
    alert_type = "order_filled_bto" if action.upper() == "BTO" else "order_filled_stc"
    broker_label = broker.upper() if broker else 'Unknown'
    
    is_option = bool(strike and expiry and opt_type)
    unit_label = "contracts" if is_option else "shares"
    
    option_str = ""
    if is_option:
        option_str = f" ${strike}{opt_type} {expiry}"
    
    title = f"[{broker_label}] {action.upper()} FILLED: {symbol}{option_str}"
    message = f"**{broker_label}**: {quantity} {unit_label} @ ${price:.2f}"
    
    details = {
        'Qty': quantity,
        'Fill Price': f"${price:.2f}"
    }
    
    if pnl is not None and action.upper() == "STC":
        details['P&L'] = f"${pnl:.2f}"
    if pnl_percent is not None and action.upper() == "STC":
        details['Return'] = f"{pnl_percent:.1f}%"
    
    return send_critical_alert(
        alert_type=alert_type,
        title=title,
        message=message,
        symbol=symbol,
        broker=broker,
        details=details
    )


def notify_conditional_created(
    symbol: str,
    trigger_type: str,
    trigger_price: float,
    broker: str,
    order_id: int,
    stop_loss: Optional[float] = None,
    expires_at: Optional[str] = None,
    channel_id: Optional[str] = None
):
    """Notify when a conditional order is created and monitoring begins."""
    broker_label = broker.upper() if broker else 'Unknown'
    direction = "ABOVE" if trigger_type == 'over' else "BELOW"
    title = f"[{broker_label}] CONDITIONAL ORDER: {symbol} {direction} ${trigger_price:.2f}"
    message = f"**{broker_label}**: Monitoring {symbol} for price {direction.lower()} ${trigger_price:.2f}"
    
    details = {
        'Order #': order_id,
        'Trigger': f"{direction} ${trigger_price:.2f}",
        'Status': 'MONITORING'
    }
    if stop_loss:
        details['Stop Loss'] = f"{stop_loss}%"
    if expires_at:
        details['Expires'] = expires_at
    
    return send_critical_alert(
        alert_type="conditional_created",
        title=title,
        message=message,
        symbol=symbol,
        broker=broker,
        details=details
    )


def notify_conditional_triggered(
    symbol: str,
    trigger_price: float,
    current_price: float,
    broker: str,
    order_id: int
):
    """Notify when a conditional order's price condition is met."""
    broker_label = broker.upper() if broker else 'Unknown'
    title = f"[{broker_label}] CONDITIONAL TRIGGERED: {symbol} @ ${current_price:.2f}"
    message = f"**{broker_label}**: {symbol} hit ${current_price:.2f} (trigger: ${trigger_price:.2f}) — Executing order"
    
    details = {
        'Order #': order_id,
        'Trigger Price': f"${trigger_price:.2f}",
        'Current Price': f"${current_price:.2f}",
        'Status': 'EXECUTING'
    }
    
    return send_critical_alert(
        alert_type="conditional_triggered",
        title=title,
        message=message,
        symbol=symbol,
        broker=broker,
        details=details
    )


def notify_conditional_expired(
    symbol: str,
    trigger_price: float,
    broker: str,
    order_id: int,
    reason: str = "Time expired"
):
    """Notify when a conditional order expires without triggering."""
    broker_label = broker.upper() if broker else 'Unknown'
    title = f"[{broker_label}] CONDITIONAL EXPIRED: {symbol}"
    message = f"**{broker_label}**: {symbol} conditional order expired — trigger ${trigger_price:.2f} never reached"
    
    details = {
        'Order #': order_id,
        'Trigger': f"${trigger_price:.2f}",
        'Reason': reason
    }
    
    return send_critical_alert(
        alert_type="conditional_expired",
        title=title,
        message=message,
        symbol=symbol,
        broker=broker,
        details=details
    )


def notify_conditional_failed(
    symbol: str,
    broker: str,
    order_id: int,
    error: str,
    stage: str = "execution"
):
    """Notify when a conditional order fails (execution error, slippage block, etc.)."""
    broker_label = broker.upper() if broker else 'Unknown'
    title = f"[{broker_label}] CONDITIONAL FAILED: {symbol}"
    message = f"**{broker_label}**: {symbol} conditional order failed during {stage}"
    
    details = {
        'Order #': order_id,
        'Stage': stage.upper(),
        'Error': error[:100]
    }
    
    return send_critical_alert(
        alert_type="conditional_failed",
        title=title,
        message=message,
        symbol=symbol,
        broker=broker,
        details=details
    )


def notify_conditional_cancelled(
    symbol: str,
    broker: str,
    order_id: int
):
    """Notify when a conditional order is manually cancelled."""
    broker_label = broker.upper() if broker else 'Unknown'
    title = f"[{broker_label}] CONDITIONAL CANCELLED: {symbol}"
    message = f"**{broker_label}**: {symbol} conditional order #{order_id} cancelled"
    
    details = {
        'Order #': order_id,
        'Status': 'CANCELLED'
    }
    
    return send_critical_alert(
        alert_type="conditional_cancelled",
        title=title,
        message=message,
        symbol=symbol,
        broker=broker,
        details=details
    )


def notify_profit_target_hit(
    symbol: str,
    broker: str,
    target_tier: int,
    profit_percent: float,
    exit_price: float,
    quantity: int,
    channel: Optional[str] = None
):
    """Notify when a profit target is hit"""
    broker_label = broker.upper() if broker else 'Unknown'
    title = f"[{broker_label}] TARGET {target_tier} HIT: {symbol}"
    message = f"**{broker_label}** profit target {target_tier} reached at **+{profit_percent:.1f}%**"
    
    details = {
        'Tier': target_tier,
        'Profit': f"+{profit_percent:.1f}%",
        'Exit Price': f"${exit_price:.2f}",
        'Qty Sold': quantity
    }
    if channel:
        details['Channel'] = channel
    
    return send_critical_alert(
        alert_type="profit_target_hit",
        title=title,
        message=message,
        symbol=symbol,
        broker=broker,
        details=details
    )


def notify_stop_loss_failed(
    symbol: str,
    broker: str,
    error_message: str,
    entry_price: Optional[float] = None,
    current_price: Optional[float] = None,
    quantity: Optional[int] = None,
    channel: Optional[str] = None
):
    """Notify when a stop loss order fails to execute - CRITICAL alert"""
    broker_label = broker.upper() if broker else 'Unknown'
    title = f"[{broker_label}] SL FAILED: {symbol}"
    message = f"**CRITICAL**: Stop loss execution failed on **{broker_label}**!\n\n{error_message}\n\n**Manual exit may be required!**"
    
    details = {}
    if entry_price:
        details['Entry'] = f"${entry_price:.2f}"
    if current_price:
        details['Current'] = f"${current_price:.2f}"
    if quantity:
        details['Qty'] = quantity
    if channel:
        details['Channel'] = channel
    details['Error'] = error_message[:100]
    
    return send_critical_alert(
        alert_type="stop_loss_failed",
        title=title,
        message=message,
        symbol=symbol,
        broker=broker,
        details=details
    )


def notify_token_expired(
    broker: str,
    error_msg: Optional[str] = None
):
    """Notify when broker trade token expires and refresh fails"""
    broker_label = broker.upper() if broker else broker
    title = f"[{broker_label}] TOKEN EXPIRED"
    message = f"Trade token expired and auto-refresh failed. Please re-login to {broker} in Settings."
    
    details = {
        'Broker': broker,
        'Action': 'Re-login required'
    }
    if error_msg:
        details['Error'] = error_msg[:100]
    
    return send_critical_alert(
        alert_type="broker_disconnect",
        title=title,
        message=message,
        symbol="N/A",
        broker=broker,
        details=details
    )


def notify_giveback_guard_triggered(
    symbol: str,
    broker: str,
    max_profit: float,
    current_profit: float,
    giveback_pct: float,
    exit_price: float,
    quantity: int,
    channel: Optional[str] = None
):
    """Notify when giveback guard triggers an exit"""
    broker_label = broker.upper() if broker else 'Unknown'
    title = f"[{broker_label}] GIVEBACK GUARD: {symbol}"
    message = f"**{broker_label}** giveback guard triggered. Profit dropped from **+{max_profit:.1f}%** to **+{current_profit:.1f}%**"
    
    details = {
        'Max Profit': f"+{max_profit:.1f}%",
        'Current': f"+{current_profit:.1f}%",
        'Giveback': f"{giveback_pct:.1f}%",
        'Exit Price': f"${exit_price:.2f}",
        'Qty Sold': quantity
    }
    if channel:
        details['Channel'] = channel
    
    return send_critical_alert(
        alert_type="giveback_guard",
        title=title,
        message=message,
        symbol=symbol,
        broker=broker,
        details=details
    )


def notify_trailing_stop_triggered(
    symbol: str,
    broker: str,
    trail_type: str,
    profit_percent: float,
    exit_price: float,
    quantity: int,
    channel: Optional[str] = None
):
    """Notify when trailing stop triggers"""
    broker_label = broker.upper() if broker else 'Unknown'
    title = f"[{broker_label}] TRAILING STOP: {symbol}"
    type_label = "Early Trailing" if trail_type == "early" else "Trailing Stop"
    message = f"**{broker_label}** {type_label} triggered at **{'+' if profit_percent >= 0 else ''}{profit_percent:.1f}%**"
    
    details = {
        'Type': type_label,
        'P&L': f"{'+' if profit_percent >= 0 else ''}{profit_percent:.1f}%",
        'Exit Price': f"${exit_price:.2f}",
        'Qty Sold': quantity
    }
    if channel:
        details['Channel'] = channel
    
    return send_critical_alert(
        alert_type="trailing_stop",
        title=title,
        message=message,
        symbol=symbol,
        broker=broker,
        details=details
    )


def notify_dynamic_sl_triggered(
    symbol: str,
    broker: str,
    entry_price: float,
    exit_price: float,
    dynamic_sl_price: float,
    pnl_percent: float,
    quantity: int,
    channel: Optional[str] = None
):
    broker_label = broker.upper() if broker else 'Unknown'
    pnl_sign = '+' if pnl_percent >= 0 else ''
    title = f"[{broker_label}] DYNAMIC SL: {symbol}"
    message = f"**{broker_label}** Dynamic Stop Loss triggered at **${exit_price:.2f}** (SL was ${dynamic_sl_price:.2f}, P&L: {pnl_sign}{pnl_percent:.1f}%)"

    details = {
        'Entry': f"${entry_price:.2f}",
        'Exit': f"${exit_price:.2f}",
        'Dynamic SL': f"${dynamic_sl_price:.2f}",
        'P&L': f"{pnl_sign}{pnl_percent:.1f}%",
        'Qty Sold': quantity
    }
    if channel:
        details['Channel'] = channel

    return send_critical_alert(
        alert_type="dynamic_sl",
        title=title,
        message=message,
        symbol=symbol,
        broker=broker,
        details=details
    )


def notify_ema_exit_triggered(
    symbol: str,
    broker: str,
    exit_type: str,
    pnl_percent: float,
    exit_price: float,
    quantity: int,
    reason: str = '',
    channel: Optional[str] = None
):
    broker_label = broker.upper() if broker else 'Unknown'
    pnl_sign = '+' if pnl_percent >= 0 else ''
    type_label = "EMA No-Trend Exit" if 'no_trend' in exit_type else "EMA Exit"
    title = f"[{broker_label}] {type_label.upper()}: {symbol}"
    message = f"**{broker_label}** {type_label} triggered at **{pnl_sign}{pnl_percent:.1f}%**"

    details = {
        'Type': type_label,
        'Exit Price': f"${exit_price:.2f}",
        'P&L': f"{pnl_sign}{pnl_percent:.1f}%",
        'Qty Sold': quantity
    }
    if reason:
        details['Reason'] = reason
    if channel:
        details['Channel'] = channel

    return send_critical_alert(
        alert_type="ema_exit",
        title=title,
        message=message,
        symbol=symbol,
        broker=broker,
        details=details
    )
