"""
Discord SelfClient - Adapter wrapper for the legacy SelfClient.
Uses composition to wrap the proven selfbot_webull.SelfClient while enabling
progressive migration to modular components.
"""

import os
import sys
import asyncio
from typing import Optional, Dict, Any, Set

from .filters import ChannelFilter, AuthorFilter


USE_MODULAR_HANDLER = os.environ.get('USE_MODULAR_DISCORD_HANDLER', 'false').lower() == 'true'


def get_legacy_selfclient():
    """
    Import and return the legacy SelfClient class from selfbot_webull.py.
    This enables composition without circular import issues.
    
    Note: The legacy module may trigger license validation at import time.
    This function catches all exceptions to allow graceful fallback.
    """
    try:
        from src.selfbot_webull import SelfClient as LegacySelfClient
        return LegacySelfClient
    except ImportError as e:
        print(f"[DISCORD] Warning: Could not import legacy SelfClient: {e}")
        return None
    except SystemExit as e:
        print(f"[DISCORD] Warning: Legacy client requires license setup")
        return None
    except Exception as e:
        print(f"[DISCORD] Warning: Legacy client import failed: {e}")
        return None


class SelfClientAdapter:
    """
    Adapter that wraps the legacy SelfClient for progressive migration.
    
    This allows:
    - Using the proven legacy implementation as the default
    - Gradually enabling modular handlers via feature flags
    - Testing new components in parallel with legacy behavior
    - No feature regression during migration
    """
    
    def __init__(self, **kwargs):
        self._legacy_client = None
        self._modular_components = {}
        self._use_modular = USE_MODULAR_HANDLER
        
        LegacySelfClient = get_legacy_selfclient()
        if LegacySelfClient:
            self._legacy_client = LegacySelfClient(**kwargs)
            print(f"[DISCORD ADAPTER] ✓ Wrapped legacy SelfClient")
        else:
            print(f"[DISCORD ADAPTER] ⚠️ Legacy client not available, using standalone mode")
    
    def __getattr__(self, name):
        """Delegate attribute access to the wrapped legacy client."""
        if self._legacy_client and hasattr(self._legacy_client, name):
            return getattr(self._legacy_client, name)
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")
    
    @property
    def use_modular_handler(self) -> bool:
        """Check if modular handler is enabled."""
        return self._use_modular
    
    @use_modular_handler.setter
    def use_modular_handler(self, value: bool):
        """Enable or disable modular handler."""
        self._use_modular = value
        print(f"[DISCORD ADAPTER] Modular handler: {'enabled' if value else 'disabled'}")
    
    def get_legacy_client(self):
        """Get the wrapped legacy client instance."""
        return self._legacy_client
    
    def add_modular_component(self, name: str, component: Any):
        """Register a modular component for gradual migration."""
        self._modular_components[name] = component
        print(f"[DISCORD ADAPTER] Registered modular component: {name}")
    
    async def run(self, token: str):
        """Run the Discord client."""
        if self._legacy_client:
            await self._legacy_client.start(token)
        else:
            raise RuntimeError("No Discord client available to run")


try:
    import discord
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False
    discord = None


if DISCORD_AVAILABLE:
    class SelfClient(discord.Client):
        """
        Standalone Discord self-bot client with modular architecture.
        
        This is used when:
        - The legacy selfbot_webull.py is not available
        - A clean modular implementation is preferred
        - Testing modular components in isolation
        
        For production use, prefer SelfClientAdapter which wraps the legacy client.
        """
        
        def __init__(self, **kwargs):
            if 'intents' not in kwargs and hasattr(discord, 'Intents'):
                intents = discord.Intents.default()
                intents.guilds = True
                intents.messages = True
                intents.message_content = True
                kwargs['intents'] = intents
            
            super().__init__(**kwargs)
            
            self.order_queue: Optional[asyncio.Queue] = None
            self.broker: Optional[Any] = None
            self.paper_broker: Optional[Any] = None
            self.broker_ready: Optional[asyncio.Event] = None
            self.processing_ready: Optional[asyncio.Event] = None
            self._send_lock: Optional[asyncio.Lock] = None
            
            self._processed_messages: Set[int] = set()
            self._max_processed_cache = 1000
            self._executing_commands: Set[int] = set()
            self._recent_sends: Dict[str, float] = {}
            self._send_dedupe_window = 300.0
            
            self.trade_analyzer: Optional[Any] = None
            self.sentiment_analyzer: Optional[Any] = None
            self.trade_tracker: Optional[Any] = None
            self.av_scanner: Optional[Any] = None
            self.swing_analyzer: Optional[Any] = None
            self.news_service: Optional[Any] = None
            self.fundamental_analyzer: Optional[Any] = None
            self.sync_service: Optional[Any] = None
            
            self.db: Optional[Any] = None
            
            self.channel_filter: Optional[ChannelFilter] = None
            self.author_filter: Optional[AuthorFilter] = None
            
            self._initialize_database()
            self._initialize_filters()
        
        def _initialize_database(self) -> None:
            """Initialize database connection for GUI integration."""
            try:
                from gui_app.database import Database
                self.db = Database()
                print("[DATABASE] ✓ Database initialized")
            except Exception as e:
                print(f"[DATABASE] ⚠️  Failed to initialize: {e}")
                self.db = None
        
        def _initialize_filters(self) -> None:
            """Initialize channel and author filters."""
            self.channel_filter = ChannelFilter(self.db)
            self.author_filter = AuthorFilter(self.db)
        
        def _get_channel_info(self, channel_id: int) -> Optional[dict]:
            """Get full channel information from database."""
            if self.channel_filter:
                return self.channel_filter.get_channel_info(channel_id)
            return None
        
        def _is_message_duplicate(self, message_id: int) -> bool:
            """Check if message has already been processed."""
            if message_id in self._processed_messages:
                return True
            
            self._processed_messages.add(message_id)
            
            if len(self._processed_messages) > self._max_processed_cache:
                to_remove = list(self._processed_messages)[:self._max_processed_cache // 2]
                for msg_id in to_remove:
                    self._processed_messages.discard(msg_id)
            
            return False
        
        async def setup(self) -> None:
            """Initialize async components after event loop is running."""
            self.order_queue = asyncio.Queue()
            self.broker_ready = asyncio.Event()
            self.processing_ready = asyncio.Event()
            self._send_lock = asyncio.Lock()
            print("[ASYNC] ✓ Queue and events created in event loop")
        
        async def on_ready(self) -> None:
            """Handle Discord ready event."""
            if self.user:
                print(f"\n[Discord] ✓ Logged in as {self.user} (id={self.user.id})")
            else:
                print(f"\n[Discord] ✓ Logged in")
            
            await self.setup()
        
        async def on_error(self, event_name: str, *args, **kwargs) -> None:
            """Log Discord gateway errors."""
            import traceback
            print(f"\n[Discord ERROR] Event '{event_name}' raised an exception:")
            print(traceback.format_exc())
        
        async def on_disconnect(self) -> None:
            """Log when Discord websocket connection is lost."""
            print(f"\n[Discord DISCONNECT] ⚠️  Websocket connection lost!")
        
        async def on_resumed(self) -> None:
            """Log when Discord websocket reconnects."""
            print(f"\n[Discord RESUMED] ✓ Websocket connection restored!")
        
        async def on_message(self, message) -> None:
            """Handle incoming Discord messages (minimal implementation)."""
            channel_name = getattr(message.channel, 'name', 'DM')
            print(f"[Discord] Message in #{channel_name}")
else:
    SelfClient = None


__all__ = ['SelfClient', 'SelfClientAdapter', 'get_legacy_selfclient']
