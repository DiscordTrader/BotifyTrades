"""
Discord module - Discord self-bot client and message handling
Contains SelfClient, message routing, command handlers, and filters.

This module provides two approaches:
1. SelfClientAdapter - Wraps the legacy selfbot_webull.SelfClient for progressive migration
2. SelfClient - Standalone modular implementation for testing and new development

For production, use SelfClientAdapter to maintain feature parity with the proven legacy code.
"""

from .client import SelfClient, SelfClientAdapter, get_legacy_selfclient
from .filters import (
    ChannelFilter,
    AuthorFilter,
    is_message_allowed,
    get_channel_settings,
)
from .message_handler import (
    MessageHandler,
    parse_structured_alert,
)

__all__ = [
    'SelfClient',
    'SelfClientAdapter',
    'get_legacy_selfclient',
    'ChannelFilter',
    'AuthorFilter', 
    'is_message_allowed',
    'get_channel_settings',
    'MessageHandler',
    'parse_structured_alert',
]
