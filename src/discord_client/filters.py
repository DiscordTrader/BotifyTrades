"""
Message filtering and channel settings for Discord bot.
Handles author filtering, channel categories, and permission checks.
"""

import os
import sys
from typing import Optional, Dict, List, Any, Set

try:
    from gui_app.database import Database, get_connection
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False


class ChannelFilter:
    """Filters messages based on channel configuration from database."""
    
    def __init__(self, db: Optional['Database'] = None):
        self.db = db
        self._channel_cache: Dict[str, dict] = {}
        self._cache_ttl = 60  # seconds
        self._last_cache_refresh = 0
    
    def get_channel_info(self, channel_id: int) -> Optional[dict]:
        """Get full channel information from database including dual-mode flags."""
        if not self.db:
            return None
        
        try:
            channels = self.db.get_channels()
            for channel in channels:
                if channel['discord_channel_id'] == str(channel_id) and channel['is_active']:
                    return channel
            return None
        except Exception as e:
            print(f"[FILTER] Error checking channel info: {e}")
            return None
    
    def get_channel_category(self, channel_id: int) -> Optional[str]:
        """Get channel category from database (EXECUTE or TRACK) - legacy method."""
        channel_info = self.get_channel_info(channel_id)
        return channel_info['category'] if channel_info else None
    
    def is_channel_enabled(self, channel_id: int) -> bool:
        """Check if channel is active and configured."""
        return self.get_channel_info(channel_id) is not None
    
    def get_channel_broker(self, channel_id: int) -> Optional[str]:
        """Get the broker configured for this channel."""
        channel_info = self.get_channel_info(channel_id)
        if channel_info:
            return channel_info.get('broker', 'webull')
        return None
    
    def get_channel_risk_settings(self, channel_id: int) -> dict:
        """Get per-channel risk management settings."""
        channel_info = self.get_channel_info(channel_id)
        if not channel_info:
            return {}
        
        return {
            'profit_target_1_pct': channel_info.get('profit_target_1_pct', 0),
            'profit_target_2_pct': channel_info.get('profit_target_2_pct', 0),
            'profit_target_3_pct': channel_info.get('profit_target_3_pct', 0),
            'stop_loss_pct': channel_info.get('stop_loss_pct', 0),
            'trailing_stop_pct': channel_info.get('trailing_stop_pct', 0),
            'trailing_activation_pct': channel_info.get('trailing_activation_pct', 0),
        }


class AuthorFilter:
    """Filters messages based on author configuration from database."""
    
    def __init__(self, db: Optional['Database'] = None):
        self.db = db
        self._allowed_authors: Dict[str, Set[str]] = {}  # channel_id -> set of author_ids
        self._allowed_guilds: Set[str] = set()
    
    def is_author_allowed(self, channel_id: int, author_id: int) -> bool:
        """Check if author is allowed to post signals in this channel."""
        if not self.db:
            return True  # Allow all if no database
        
        try:
            channel_info = None
            channels = self.db.get_channels()
            for channel in channels:
                if channel['discord_channel_id'] == str(channel_id) and channel['is_active']:
                    channel_info = channel
                    break
            
            if not channel_info:
                return False
            
            # Check if author filtering is enabled for this channel
            allowed_authors_str = channel_info.get('allowed_authors', '')
            if not allowed_authors_str or allowed_authors_str.strip() == '':
                return True  # No author filtering = allow all
            
            allowed_authors = set(
                a.strip() for a in allowed_authors_str.split(',') 
                if a.strip()
            )
            
            return str(author_id) in allowed_authors
            
        except Exception as e:
            print(f"[FILTER] Error checking author permissions: {e}")
            return True  # Default to allow on error
    
    def is_guild_allowed(self, guild_id: int) -> bool:
        """Check if guild (server) is allowed."""
        if not self.db:
            return True
        
        try:
            allowed_guilds_str = self.db.get_setting('allowed_guild_ids', '')
            if not allowed_guilds_str or allowed_guilds_str.strip() == '':
                return True  # No guild filtering = allow all
            
            allowed_guilds = set(
                g.strip() for g in allowed_guilds_str.split(',')
                if g.strip()
            )
            
            return str(guild_id) in allowed_guilds
            
        except Exception as e:
            print(f"[FILTER] Error checking guild permissions: {e}")
            return True


def is_message_allowed(
    channel_id: int,
    author_id: int,
    guild_id: Optional[int] = None,
    db: Optional['Database'] = None
) -> bool:
    """
    Check if a message should be processed based on channel and author filters.
    
    Args:
        channel_id: Discord channel ID
        author_id: Discord user ID of message author
        guild_id: Discord guild ID (optional)
        db: Database instance (optional, will create if needed)
        
    Returns:
        True if message should be processed, False otherwise
    """
    if not DATABASE_AVAILABLE:
        return True
    
    if db is None:
        try:
            db = Database()
        except Exception:
            return True
    
    channel_filter = ChannelFilter(db)
    author_filter = AuthorFilter(db)
    
    # Check channel is enabled
    if not channel_filter.is_channel_enabled(channel_id):
        return False
    
    # Check author is allowed
    if not author_filter.is_author_allowed(channel_id, author_id):
        return False
    
    # Check guild is allowed (if provided)
    if guild_id is not None and not author_filter.is_guild_allowed(guild_id):
        return False
    
    return True


def get_channel_settings(channel_id: int, db: Optional['Database'] = None) -> dict:
    """
    Get all settings for a channel including risk management.
    
    Args:
        channel_id: Discord channel ID
        db: Database instance (optional)
        
    Returns:
        Dictionary of channel settings or empty dict if not found
    """
    if not DATABASE_AVAILABLE:
        return {}
    
    if db is None:
        try:
            db = Database()
        except Exception:
            return {}
    
    channel_filter = ChannelFilter(db)
    return channel_filter.get_channel_info(channel_id) or {}
