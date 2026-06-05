"""
Message handler for Discord signals.
Routes incoming messages to appropriate signal parsers and command handlers.
"""

import re
from typing import Optional, Dict, Any, Tuple, List

try:
    from src.signals.parser import parse_option_signal, parse_stock_signal
except ImportError:
    parse_option_signal = None
    parse_stock_signal = None


class MessageHandler:
    """
    Handles routing and processing of Discord messages.
    Separates command detection, signal parsing, and action execution.
    """
    
    def __init__(self, client: Any):
        self.client = client
        self.command_prefix = '!'
        
        self._command_handlers = {
            'analyze': self._handle_analyze,
            'ask': self._handle_ask,
            'scanflow': self._handle_scanflow,
            'analyze_trade': self._handle_analyze_trade,
            'convert': self._handle_convert,
        }
    
    def is_command(self, content: str) -> bool:
        """Check if message content is a command."""
        return content.strip().startswith(self.command_prefix)
    
    def parse_command(self, content: str) -> Tuple[Optional[str], str]:
        """
        Parse command name and arguments from message content.
        
        Returns:
            Tuple of (command_name, arguments) or (None, '') if not a command
        """
        if not self.is_command(content):
            return (None, '')
        
        content = content.strip()[len(self.command_prefix):]
        parts = content.split(maxsplit=1)
        
        if not parts:
            return (None, '')
        
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ''
        
        return (cmd, args)
    
    async def handle_message(self, message: Any, channel_info: Optional[dict] = None) -> bool:
        """
        Process a Discord message and route to appropriate handler.
        
        Args:
            message: Discord message object
            channel_info: Channel configuration from database
            
        Returns:
            True if message was handled, False otherwise
        """
        content = message.content.strip()
        
        if self.is_command(content):
            return await self._handle_command(message, content)
        
        return await self._handle_signal(message, content, channel_info)
    
    async def _handle_command(self, message: Any, content: str) -> bool:
        """Route command to appropriate handler."""
        cmd, args = self.parse_command(content)
        
        if cmd in self._command_handlers:
            try:
                await self._command_handlers[cmd](message, args)
                return True
            except Exception as e:
                print(f"[CMD] Error handling {cmd}: {e}")
                await message.channel.send(f"❌ Error: {str(e)}")
                return True
        
        return False
    
    async def _handle_signal(self, message: Any, content: str, channel_info: Optional[dict]) -> bool:
        """Parse and process trading signals."""
        opt_signal = None
        stock_signal = None
        
        if parse_option_signal:
            opt_signal = parse_option_signal(content)
        
        if not opt_signal and parse_stock_signal:
            stock_signal = parse_stock_signal(content)
        
        signal = opt_signal or stock_signal
        
        if signal:
            return await self._execute_signal(message, signal, channel_info)
        
        return False
    
    async def _execute_signal(self, message: Any, signal: dict, channel_info: Optional[dict]) -> bool:
        """Execute a parsed trading signal."""
        execute_enabled = channel_info.get('execute_enabled', 0) if channel_info else False
        track_enabled = channel_info.get('track_enabled', 0) if channel_info else False
        
        print(f"[SIGNAL] Parsed: {signal['action']} {signal.get('qty', 1)} {signal['symbol']}")
        print(f"[SIGNAL] Execute: {execute_enabled}, Track: {track_enabled}")
        
        if execute_enabled:
            if self.client.order_queue:
                await self.client.order_queue.put(signal)
                print(f"[SIGNAL] ✓ Order queued for execution")
        
        if track_enabled:
            print(f"[SIGNAL] ✓ Signal tracked for P&L monitoring")
        
        return True
    
    async def _handle_analyze(self, message: Any, args: str) -> None:
        """Handle !analyze command."""
        parts = args.split()
        if not parts:
            await message.channel.send("❌ Usage: `!analyze [SYMBOL] [TIMEFRAME]`\nExample: `!analyze AAPL 1day`")
            return
        
        symbol = parts[0].upper()
        timeframe = parts[1] if len(parts) > 1 else '1day'
        
        if hasattr(self.client, 'handle_analyze_command'):
            await self.client.handle_analyze_command(message, symbol, timeframe)
        else:
            await message.channel.send(f"📊 Analyzing {symbol} on {timeframe} timeframe...")
    
    async def _handle_ask(self, message: Any, args: str) -> None:
        """Handle !ask command."""
        if not args:
            await message.channel.send("❌ Usage: `!ask [QUESTION]`\nExample: `!ask What are the best indicators for day trading?`")
            return
        
        if hasattr(self.client, 'handle_ask_command'):
            await self.client.handle_ask_command(message, args)
        else:
            await message.channel.send("🤖 AI assistant is not available.")
    
    async def _handle_scanflow(self, message: Any, args: str) -> None:
        """Handle !scanflow command."""
        symbols_str = args if args else None
        
        if hasattr(self.client, 'handle_scanflow_command'):
            await self.client.handle_scanflow_command(message, symbols_str)
        else:
            await message.channel.send("📈 Scanflow is not available.")
    
    async def _handle_analyze_trade(self, message: Any, args: str) -> None:
        """Handle !analyze_trade command."""
        if not args:
            await message.channel.send("❌ Usage: `!analyze_trade [SYMBOL]`\nExample: `!analyze_trade NVDA`")
            return
        
        symbol = args.strip().upper()
        
        if hasattr(self.client, 'handle_analyze_trade_command'):
            await self.client.handle_analyze_trade_command(message, symbol)
        else:
            await message.channel.send("🔍 Trade analysis is not available.")
    
    async def _handle_convert(self, message: Any, args: str) -> None:
        """Handle !convert command."""
        if not args:
            await message.channel.send("❌ Usage: `!convert [TEXT]`\nExample: `!convert Added back 20% META`")
            return
        
        if hasattr(self.client, 'handle_convert_command'):
            await self.client.handle_convert_command(message, args)
        else:
            await message.channel.send("🔄 Signal conversion is not available.")


def parse_structured_alert(text: str) -> dict:
    """
    Parse structured alert format used by some signal providers.
    
    Format: "TRADE IDEA: [ACTION] [SYMBOL] ..."
    
    Args:
        text: Raw message text
        
    Returns:
        Dictionary with parsed alert fields or empty dict
    """
    result = {
        'type': None,
        'symbol': None,
        'action': None,
        'entry': None,
        'stop_loss': None,
        'targets': []
    }
    
    if 'TRADE IDEA' not in text.upper():
        return result
    
    lines = text.strip().split('\n')
    
    for line in lines:
        line_upper = line.upper()
        
        symbol_match = re.search(r'\$([A-Z]+)', line)
        if symbol_match and not result['symbol']:
            result['symbol'] = symbol_match.group(1)
        
        if 'BUY' in line_upper or 'LONG' in line_upper:
            result['action'] = 'BTO'
        elif 'SELL' in line_upper or 'SHORT' in line_upper:
            result['action'] = 'STC'
        
        entry_match = re.search(r'ENTRY[:\s]+\$?(\d+\.?\d*)', line_upper)
        if entry_match:
            result['entry'] = float(entry_match.group(1))
        
        stop_match = re.search(r'STOP[:\s]+\$?(\d+\.?\d*)', line_upper)
        if stop_match:
            result['stop_loss'] = float(stop_match.group(1))
        
        target_match = re.search(r'TARGET\s*\d*[:\s]+\$?(\d+\.?\d*)', line_upper)
        if target_match:
            result['targets'].append(float(target_match.group(1)))
    
    if result['symbol'] and result['action']:
        result['type'] = 'structured_alert'
    
    return result
