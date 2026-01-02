"""
Telegram module - Telegram user client for reading trading signals.
Uses Telethon to connect as a user account (not a bot) to read messages
from private groups and channels.

This module provides:
- TelegramListener - Connects to Telegram and listens for trading signals
- TelegramMessage - Normalized message format for signal processing
"""

from .listener import TelegramListener, TelegramMessage

__all__ = [
    'TelegramListener',
    'TelegramMessage',
]
