#!/usr/bin/env python3
"""
Fetch recent messages from a Discord channel for format analysis.
Uses the bot's Discord token to fetch channel history.
"""
import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import discord
except ImportError:
    print("Error: discord.py-self not installed")
    sys.exit(1)

CHANNEL_ID = 1239624229583061052
MESSAGE_LIMIT = 50

def get_discord_token():
    """Load Discord token using same method as main bot."""
    try:
        from gui_app.broker_credentials_service import get_all_credentials_for_startup
        credentials = get_all_credentials_for_startup()
        token = credentials.get('DISCORD_USER_TOKEN', '').strip()
        if token:
            return token
    except Exception as e:
        print(f"Could not load from credentials service: {e}")
    
    # Fallback to environment variable
    import os
    token = os.getenv('DISCORD_USER_TOKEN', '').strip()
    if token:
        return token
    
    return None

class MessageFetcher(discord.Client):
    def __init__(self, channel_id, limit):
        super().__init__()
        self.channel_id = channel_id
        self.limit = limit
        self.messages = []
        
    async def on_ready(self):
        print(f"Logged in as {self.user}")
        print(f"Fetching {self.limit} messages from channel {self.channel_id}...")
        
        try:
            channel = self.get_channel(self.channel_id)
            if not channel:
                channel = await self.fetch_channel(self.channel_id)
            
            if not channel:
                print(f"Error: Could not access channel {self.channel_id}")
                await self.close()
                return
            
            print(f"Channel found: #{channel.name} in {channel.guild.name if hasattr(channel, 'guild') else 'DM'}")
            print("=" * 80)
            
            async for message in channel.history(limit=self.limit):
                # Extract embed content
                embed_texts = []
                for embed in message.embeds:
                    if embed.title:
                        embed_texts.append(f"[TITLE] {embed.title}")
                    if embed.description:
                        embed_texts.append(f"[DESC] {embed.description}")
                    for field in embed.fields:
                        embed_texts.append(f"[{field.name}] {field.value}")
                
                full_content = message.content + "\n" + "\n".join(embed_texts) if embed_texts else message.content
                
                self.messages.append({
                    'content': full_content,
                    'author': str(message.author),
                    'author_id': str(message.author.id),
                    'timestamp': str(message.created_at),
                    'id': str(message.id)
                })
                
                # Print each message
                print(f"\n[{message.created_at.strftime('%Y-%m-%d %H:%M')}] {message.author}:")
                print(f"  {message.content[:200]}{'...' if len(message.content) > 200 else ''}")
                if embed_texts:
                    for et in embed_texts[:5]:
                        print(f"  EMBED: {et[:200]}")
            
            print("\n" + "=" * 80)
            print(f"Fetched {len(self.messages)} messages")
            
            # Analyze common patterns
            print("\n=== FORMAT ANALYSIS ===")
            self.analyze_formats()
            
        except discord.Forbidden:
            print(f"Error: No permission to access channel {self.channel_id}")
        except Exception as e:
            print(f"Error fetching messages: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await self.close()
    
    def analyze_formats(self):
        """Analyze message formats to identify signal patterns."""
        import re
        
        patterns = {
            'BTO/STC standard': r'(BTO|STC)\s+\$?\w+\s+\$?[\d.]+[CPcp]',
            'DTE format': r'\d+DTE',
            'Entry price @': r'@\s*\$?[\d.]+',
            'Option chain': r'\$?\w+\s+\$?[\d.]+\s*[CPcp]\s*\d{1,2}/\d{1,2}',
            'Multi-leg': r'(spread|butterfly|iron\s*condor)',
            'Stock alert': r'(buy|sell|long|short)\s+\$?\w+',
            'Price targets': r'(PT|TP|target|take\s*profit)[:=]?\s*\$?[\d.]+',
            'Stop loss': r'(SL|stop|stoploss|stop\s*loss)[:=]?\s*\$?[\d.]+',
            'Quantity': r'(\d+)\s*(contracts?|shares?|lots?)',
        }
        
        format_counts = {name: 0 for name in patterns}
        example_messages = {name: [] for name in patterns}
        
        for msg in self.messages:
            content = msg['content']
            for name, pattern in patterns.items():
                if re.search(pattern, content, re.IGNORECASE):
                    format_counts[name] += 1
                    if len(example_messages[name]) < 3:
                        example_messages[name].append(content[:200])
        
        print("\nDetected patterns:")
        for name, count in sorted(format_counts.items(), key=lambda x: -x[1]):
            if count > 0:
                print(f"  {name}: {count} occurrences")
                for ex in example_messages[name][:2]:
                    print(f"    Example: {ex[:100]}...")
        
        # Look for unique formats
        print("\n=== UNIQUE MESSAGE FORMATS ===")
        unique_formats = set()
        for msg in self.messages:
            content = msg['content'].strip()
            if content and len(content) > 10:
                # Normalize to find structure
                normalized = re.sub(r'\d+', 'N', content)
                normalized = re.sub(r'\$[\d.]+', '$N', normalized)
                if normalized not in unique_formats:
                    unique_formats.add(normalized)
                    if len(unique_formats) <= 10:
                        print(f"\nFormat: {content[:300]}")

def main():
    token = get_discord_token()
    if not token:
        print("Error: Discord token not found. Check credentials in GUI settings.")
        sys.exit(1)
    
    print(f"Using token: {token[:20]}...{token[-10:]}")
    
    client = MessageFetcher(CHANNEL_ID, MESSAGE_LIMIT)
    
    try:
        client.run(token)
    except discord.LoginFailure:
        print("Error: Invalid Discord token")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
