"""
Signal Conversation State Manager

Tracks conversation context per channel+author for sequential message monitoring.
Enables delayed SL/PT updates and correlates follow-up messages with active orders.

Key Features:
- Maintains sliding window of recent messages per channel+author
- Correlates follow-up messages with active conditional orders
- Supports delayed SL/PT updates within configurable timeout
- Thread-safe for concurrent message processing
"""

import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class ConversationMessage:
    """Represents a message in the conversation context."""
    message_id: int
    channel_id: int
    author_id: int
    timestamp: datetime
    text: str
    symbol: Optional[str] = None
    order_id: Optional[int] = None
    consumed: bool = False


@dataclass
class SignalContext:
    """Context for an active signal/order awaiting follow-up updates."""
    symbol: str
    order_id: Optional[int]
    channel_id: int
    author_id: int
    created_at: datetime
    last_update: datetime
    stop_loss_value: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    profit_targets: List[float] = field(default_factory=list)
    linked_message_ids: List[int] = field(default_factory=list)


class SignalConversationStateManager:
    """
    Manages conversation state for sequential message monitoring.
    
    Tracks recent messages per channel+author and correlates follow-up
    messages with active orders for delayed SL/PT updates.
    """
    
    def __init__(
        self,
        max_messages_per_context: int = 10,
        follow_up_timeout_seconds: int = 300,  # 5 minutes
        cleanup_interval_seconds: int = 60
    ):
        self._lock = threading.RLock()
        self.max_messages = max_messages_per_context
        self.follow_up_timeout = follow_up_timeout_seconds
        self.cleanup_interval = cleanup_interval_seconds
        
        self._messages: Dict[Tuple[int, int], OrderedDict[int, ConversationMessage]] = {}
        self._active_contexts: Dict[Tuple[int, int, str], SignalContext] = {}
        self._order_to_context: Dict[int, Tuple[int, int, str]] = {}
        
        self._last_cleanup = time.time()
    
    def _get_context_key(self, channel_id: int, author_id: int) -> Tuple[int, int]:
        return (channel_id, author_id)
    
    def _get_signal_key(self, channel_id: int, author_id: int, symbol: str) -> Tuple[int, int, str]:
        return (channel_id, author_id, symbol.upper())
    
    def _maybe_cleanup(self):
        now = time.time()
        if now - self._last_cleanup < self.cleanup_interval:
            return
        
        self._last_cleanup = now
        cutoff = datetime.now() - timedelta(seconds=self.follow_up_timeout * 2)
        
        expired_contexts = []
        for key, ctx in list(self._active_contexts.items()):
            if ctx.last_update < cutoff:
                expired_contexts.append(key)
        
        for key in expired_contexts:
            ctx = self._active_contexts.pop(key, None)
            if ctx and ctx.order_id:
                self._order_to_context.pop(ctx.order_id, None)
        
        for ctx_key, messages in list(self._messages.items()):
            expired_msgs = [
                msg_id for msg_id, msg in messages.items()
                if msg.timestamp < cutoff
            ]
            for msg_id in expired_msgs:
                messages.pop(msg_id, None)
            
            if not messages:
                self._messages.pop(ctx_key, None)
    
    def add_message(
        self,
        message_id: int,
        channel_id: int,
        author_id: int,
        text: str,
        symbol: Optional[str] = None,
        order_id: Optional[int] = None
    ) -> ConversationMessage:
        """
        Add a message to the conversation context.
        
        Returns the created ConversationMessage.
        """
        with self._lock:
            self._maybe_cleanup()
            
            ctx_key = self._get_context_key(channel_id, author_id)
            
            if ctx_key not in self._messages:
                self._messages[ctx_key] = OrderedDict()
            
            msg = ConversationMessage(
                message_id=message_id,
                channel_id=channel_id,
                author_id=author_id,
                timestamp=datetime.now(),
                text=text,
                symbol=symbol.upper() if symbol else None,
                order_id=order_id
            )
            
            self._messages[ctx_key][message_id] = msg
            
            while len(self._messages[ctx_key]) > self.max_messages:
                self._messages[ctx_key].popitem(last=False)
            
            return msg
    
    def register_signal_context(
        self,
        channel_id: int,
        author_id: int,
        symbol: str,
        order_id: Optional[int] = None,
        stop_loss_value: Optional[float] = None,
        stop_loss_pct: Optional[float] = None,
        profit_targets: Optional[List[float]] = None,
        message_id: Optional[int] = None
    ) -> SignalContext:
        """
        Register a new signal context for follow-up monitoring.
        
        Call this when a new conditional order is created.
        """
        with self._lock:
            sig_key = self._get_signal_key(channel_id, author_id, symbol)
            
            ctx = SignalContext(
                symbol=symbol.upper(),
                order_id=order_id,
                channel_id=channel_id,
                author_id=author_id,
                created_at=datetime.now(),
                last_update=datetime.now(),
                stop_loss_value=stop_loss_value,
                stop_loss_pct=stop_loss_pct,
                profit_targets=list(profit_targets) if profit_targets else [],
                linked_message_ids=[message_id] if message_id else []
            )
            
            self._active_contexts[sig_key] = ctx
            
            if order_id:
                self._order_to_context[order_id] = sig_key
            
            print(f"[CONV STATE] Registered context for {symbol} "
                  f"(channel={channel_id}, order={order_id})")
            
            return ctx
    
    def get_signal_context(
        self,
        channel_id: int,
        author_id: int,
        symbol: Optional[str] = None
    ) -> Optional[SignalContext]:
        """
        Get the active signal context for a channel+author+symbol.
        
        If symbol is None, returns the most recent context for the channel+author.
        """
        with self._lock:
            if symbol:
                sig_key = self._get_signal_key(channel_id, author_id, symbol)
                ctx = self._active_contexts.get(sig_key)
                
                if ctx:
                    timeout_cutoff = datetime.now() - timedelta(seconds=self.follow_up_timeout)
                    if ctx.last_update >= timeout_cutoff:
                        return ctx
                    else:
                        self._active_contexts.pop(sig_key, None)
                        if ctx.order_id:
                            self._order_to_context.pop(ctx.order_id, None)
                
                return None
            
            timeout_cutoff = datetime.now() - timedelta(seconds=self.follow_up_timeout)
            best_ctx = None
            best_time = None
            
            for sig_key, ctx in list(self._active_contexts.items()):
                if sig_key[0] != channel_id or sig_key[1] != author_id:
                    continue
                
                if ctx.last_update < timeout_cutoff:
                    continue
                
                if best_time is None or ctx.last_update > best_time:
                    best_ctx = ctx
                    best_time = ctx.last_update
            
            return best_ctx
    
    def get_context_by_order_id(self, order_id: int) -> Optional[SignalContext]:
        """Get signal context by order ID."""
        with self._lock:
            sig_key = self._order_to_context.get(order_id)
            if sig_key:
                return self._active_contexts.get(sig_key)
            return None
    
    def update_signal_context(
        self,
        channel_id: int,
        author_id: int,
        symbol: str,
        stop_loss_value: Optional[float] = None,
        stop_loss_pct: Optional[float] = None,
        profit_target: Optional[float] = None,
        message_id: Optional[int] = None
    ) -> Optional[SignalContext]:
        """
        Update an existing signal context with new SL/PT values.
        
        Returns the updated context, or None if no matching context found.
        """
        with self._lock:
            sig_key = self._get_signal_key(channel_id, author_id, symbol)
            ctx = self._active_contexts.get(sig_key)
            
            if not ctx:
                return None
            
            timeout_cutoff = datetime.now() - timedelta(seconds=self.follow_up_timeout)
            if ctx.last_update < timeout_cutoff:
                self._active_contexts.pop(sig_key, None)
                if ctx.order_id:
                    self._order_to_context.pop(ctx.order_id, None)
                return None
            
            if stop_loss_value is not None:
                ctx.stop_loss_value = stop_loss_value
            if stop_loss_pct is not None:
                ctx.stop_loss_pct = stop_loss_pct
            if profit_target is not None:
                if profit_target not in ctx.profit_targets:
                    ctx.profit_targets.append(profit_target)
            
            ctx.last_update = datetime.now()
            
            if message_id and message_id not in ctx.linked_message_ids:
                ctx.linked_message_ids.append(message_id)
            
            print(f"[CONV STATE] Updated context for {symbol}: "
                  f"SL=${ctx.stop_loss_value}, PT={ctx.profit_targets}")
            
            return ctx
    
    def remove_signal_context(
        self,
        channel_id: int = None,
        author_id: int = None,
        symbol: str = None,
        order_id: int = None
    ) -> bool:
        """
        Remove a signal context (e.g., when order is cancelled or filled).
        
        Can specify by channel+author+symbol or by order_id.
        """
        with self._lock:
            if order_id:
                sig_key = self._order_to_context.pop(order_id, None)
                if sig_key:
                    self._active_contexts.pop(sig_key, None)
                    print(f"[CONV STATE] Removed context for order #{order_id}")
                    return True
            
            if channel_id is not None and author_id is not None and symbol:
                sig_key = self._get_signal_key(channel_id, author_id, symbol)
                ctx = self._active_contexts.pop(sig_key, None)
                if ctx:
                    if ctx.order_id:
                        self._order_to_context.pop(ctx.order_id, None)
                    print(f"[CONV STATE] Removed context for {symbol}")
                    return True
            
            return False
    
    def get_recent_symbol_for_author(
        self,
        channel_id: int,
        author_id: int
    ) -> Optional[str]:
        """
        Get the most recently mentioned symbol by this author in this channel.
        
        Useful for correlating follow-up messages that don't specify a symbol.
        """
        with self._lock:
            ctx = self.get_signal_context(channel_id, author_id, symbol=None)
            if ctx:
                return ctx.symbol
            
            ctx_key = self._get_context_key(channel_id, author_id)
            messages = self._messages.get(ctx_key)
            
            if not messages:
                return None
            
            for msg in reversed(list(messages.values())):
                if msg.symbol:
                    return msg.symbol
            
            return None
    
    def get_pending_updates_for_order(self, order_id: int) -> Dict[str, Any]:
        """
        Get any pending SL/PT updates for an order.
        
        Returns dict with stop_loss_value, stop_loss_pct, profit_targets.
        """
        with self._lock:
            ctx = self.get_context_by_order_id(order_id)
            if not ctx:
                return {}
            
            return {
                'stop_loss_value': ctx.stop_loss_value,
                'stop_loss_pct': ctx.stop_loss_pct,
                'profit_targets': ctx.profit_targets.copy() if ctx.profit_targets else [],
            }


_conversation_state_manager: Optional[SignalConversationStateManager] = None
_manager_lock = threading.Lock()


def get_conversation_state_manager() -> SignalConversationStateManager:
    """Get the singleton conversation state manager."""
    global _conversation_state_manager
    with _manager_lock:
        if _conversation_state_manager is None:
            _conversation_state_manager = SignalConversationStateManager()
        return _conversation_state_manager


def register_signal_for_follow_up(
    channel_id: int,
    author_id: int,
    symbol: str,
    order_id: Optional[int] = None,
    stop_loss_value: Optional[float] = None,
    stop_loss_pct: Optional[float] = None,
    profit_targets: Optional[List[float]] = None,
    message_id: Optional[int] = None
) -> SignalContext:
    """
    Convenience function to register a signal for follow-up monitoring.
    """
    manager = get_conversation_state_manager()
    return manager.register_signal_context(
        channel_id=channel_id,
        author_id=author_id,
        symbol=symbol,
        order_id=order_id,
        stop_loss_value=stop_loss_value,
        stop_loss_pct=stop_loss_pct,
        profit_targets=profit_targets,
        message_id=message_id
    )


def process_follow_up_message(
    message_id: int,
    channel_id: int,
    author_id: int,
    text: str
) -> Optional[Dict[str, Any]]:
    """
    Process a potential follow-up message for SL/PT updates.
    
    Returns dict with updates if this is a valid follow-up, None otherwise.
    """
    from src.signals.parser import parse_follow_up_update
    
    manager = get_conversation_state_manager()
    
    recent_symbol = manager.get_recent_symbol_for_author(channel_id, author_id)
    
    update = parse_follow_up_update(text, context_symbol=recent_symbol)
    if not update:
        return None
    
    symbol = update.get('symbol') or recent_symbol
    if not symbol:
        return None
    
    ctx = manager.update_signal_context(
        channel_id=channel_id,
        author_id=author_id,
        symbol=symbol,
        stop_loss_value=update.get('stop_loss_update'),
        profit_target=update.get('profit_target_update'),
        message_id=message_id
    )
    
    if ctx:
        return {
            'order_id': ctx.order_id,
            'symbol': symbol,
            'stop_loss_value': update.get('stop_loss_update'),
            'stop_loss_pct_update': update.get('stop_loss_pct_update'),
            'profit_target_update': update.get('profit_target_update'),
            'profit_targets_update': update.get('profit_targets_update'),
        }
    
    return None


def cancel_signal_context(
    channel_id: int = None,
    author_id: int = None,
    symbol: str = None,
    order_id: int = None
) -> bool:
    """
    Convenience function to remove a signal context.
    """
    manager = get_conversation_state_manager()
    return manager.remove_signal_context(
        channel_id=channel_id,
        author_id=author_id,
        symbol=symbol,
        order_id=order_id
    )
