"""
Discord Trade Notification System
Sends BTO/STC messages to Discord via webhook
"""
import requests
import logging
from datetime import datetime
from typing import Optional
from .config_service import get_discord_notifications

logger = logging.getLogger(__name__)


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
    """
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
