"""
Mock Discord client for testing signal detection and routing
"""
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from datetime import datetime
import asyncio


@dataclass
class MockUser:
    """Mock Discord user"""
    id: int = 123456789
    name: str = "TestUser"
    bot: bool = False


@dataclass
class MockChannel:
    """Mock Discord channel"""
    id: int = 987654321
    name: str = "test-signals"
    guild: Any = None
    
    async def send(self, content: str = None, embed: Any = None) -> 'MockMessage':
        """Simulate sending a message"""
        return MockMessage(
            content=content,
            channel=self,
            author=MockUser(name="Bot")
        )


@dataclass
class MockEmbed:
    """Mock Discord embed"""
    title: str = ""
    description: str = ""
    fields: List[Dict[str, Any]] = field(default_factory=list)
    color: int = 0
    
    def add_field(self, name: str, value: str, inline: bool = False):
        self.fields.append({'name': name, 'value': value, 'inline': inline})


@dataclass
class MockMessage:
    """Mock Discord message"""
    id: int = None
    content: str = ""
    channel: MockChannel = None
    author: MockUser = None
    embeds: List[MockEmbed] = field(default_factory=list)
    created_at: datetime = None
    edited_at: datetime = None
    
    def __post_init__(self):
        if self.id is None:
            self.id = int(datetime.now().timestamp() * 1000000)
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.channel is None:
            self.channel = MockChannel()
        if self.author is None:
            self.author = MockUser()


class MockDiscordClient:
    """Mock Discord selfbot client for testing"""
    
    def __init__(self):
        self.user = MockUser(id=489251897820053505, name="BotifyTrades")
        self.channels: Dict[int, MockChannel] = {}
        self.messages: List[MockMessage] = []
        self._on_message_handlers: List[Callable] = []
        self._on_message_edit_handlers: List[Callable] = []
        self.is_ready = True
    
    def get_channel(self, channel_id: int) -> Optional[MockChannel]:
        """Get a channel by ID"""
        if channel_id not in self.channels:
            self.channels[channel_id] = MockChannel(id=channel_id)
        return self.channels[channel_id]
    
    def add_channel(self, channel_id: int, name: str) -> MockChannel:
        """Add a channel to the mock client"""
        channel = MockChannel(id=channel_id, name=name)
        self.channels[channel_id] = channel
        return channel
    
    async def simulate_message(
        self,
        content: str,
        channel_id: int = 987654321,
        author_name: str = "Trader",
        embeds: List[MockEmbed] = None
    ) -> MockMessage:
        """Simulate receiving a message (triggers on_message handlers)"""
        channel = self.get_channel(channel_id)
        author = MockUser(name=author_name)
        
        message = MockMessage(
            content=content,
            channel=channel,
            author=author,
            embeds=embeds or []
        )
        self.messages.append(message)
        
        for handler in self._on_message_handlers:
            await handler(message)
        
        return message
    
    async def simulate_message_edit(
        self,
        message: MockMessage,
        new_content: str
    ):
        """Simulate a message being edited"""
        old_message = MockMessage(
            id=message.id,
            content=message.content,
            channel=message.channel,
            author=message.author
        )
        message.content = new_content
        message.edited_at = datetime.now()
        
        for handler in self._on_message_edit_handlers:
            await handler(old_message, message)
    
    def on_message(self, handler: Callable):
        """Register an on_message handler"""
        self._on_message_handlers.append(handler)
        return handler
    
    def on_message_edit(self, handler: Callable):
        """Register an on_message_edit handler"""
        self._on_message_edit_handlers.append(handler)
        return handler
    
    async def wait_until_ready(self):
        """Simulate waiting for client to be ready"""
        pass
    
    def run(self, token: str):
        """Mock run method"""
        pass
    
    def reset(self):
        """Reset state for new test"""
        self.channels.clear()
        self.messages.clear()


def create_signal_message(
    signal_text: str,
    channel_id: int = 987654321,
    channel_name: str = "test-signals"
) -> MockMessage:
    """Helper to create a signal message for testing"""
    channel = MockChannel(id=channel_id, name=channel_name)
    return MockMessage(
        content=signal_text,
        channel=channel,
        author=MockUser(name="SignalProvider")
    )


def create_embed_signal(
    title: str,
    description: str,
    channel_id: int = 987654321
) -> MockMessage:
    """Helper to create an embed signal message"""
    channel = MockChannel(id=channel_id)
    embed = MockEmbed(title=title, description=description)
    return MockMessage(
        content="",
        channel=channel,
        author=MockUser(name="SignalBot"),
        embeds=[embed]
    )
