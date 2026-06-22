"""
TelegramListener - Telethon-based client for reading trading signals from Telegram.

Uses a Telegram user account (not a bot) to access private groups and channels.
Normalizes messages to a common format that can be processed by the same
signal parsers used for Discord.
"""

import asyncio
import os
import queue
import sys
from typing import Optional, Dict, Any, Callable, List, Set, Union, Tuple
from dataclasses import dataclass, field
from datetime import datetime


def _print_flush(msg: str) -> None:
    """Print with explicit flush to ensure output appears in logs."""
    # Try to use _original_print if available (set by selfbot_webull.py)
    import builtins
    printer = getattr(builtins, '_original_print', print)
    printer(msg, flush=True)
    sys.stdout.flush()


def _normalize_chat_id(chat_id: Union[int, str]) -> int:
    """
    Normalize Telegram chat ID to handle -100 prefix variations.
    Telethon supergroups/channels use -100 prefix (e.g., -1005164376330)
    but users often store without it (e.g., -5164376330).
    Returns the base ID without -100 prefix for comparison.
    """
    if isinstance(chat_id, str):
        if chat_id.startswith('@'):
            return chat_id  # Username, return as-is
        try:
            chat_id = int(chat_id)
        except ValueError:
            return chat_id  # Return as string if not convertible
    
    # Convert to positive for easier manipulation
    if chat_id < 0:
        chat_id_str = str(abs(chat_id))
        # Remove -100 prefix if present (supergroup/channel format)
        if chat_id_str.startswith('100') and len(chat_id_str) > 10:
            return -int(chat_id_str[3:])  # Strip '100' prefix
        return chat_id
    return chat_id


try:
    from telethon import TelegramClient, events
    from telethon.sessions import StringSession
    from telethon.tl.types import Message, Channel, Chat, User
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False
    TelegramClient = None
    events = None
    StringSession = None


@dataclass
class TelegramMessage:
    """
    Normalized message format compatible with signal parsing.
    Mirrors the structure expected by the signal parser.
    """
    content: str
    chat_id: int
    chat_name: str
    chat_type: str
    author_id: int
    author_name: str
    timestamp: datetime
    message_id: int
    platform: str = 'telegram'
    raw_message: Any = None
    embeds: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for signal processing."""
        return {
            'content': self.content,
            'platform': self.platform,
            'channel_id': str(self.chat_id),
            'channel_name': self.chat_name,
            'channel_type': self.chat_type,
            'author_id': str(self.author_id),
            'author_name': self.author_name,
            'timestamp': self.timestamp.isoformat(),
            'message_id': str(self.message_id),
            'embeds': self.embeds,
        }


class TelegramListener:
    """
    Telegram user client that listens for trading signals.
    
    Uses Telethon (user account, not bot API) to:
    - Connect to Telegram with user credentials
    - Listen for messages in configured channels/groups
    - Normalize messages to a format compatible with signal parsers
    - Route parsed signals to the execution queue
    """
    
    def __init__(
        self,
        api_id: Optional[str] = None,
        api_hash: Optional[str] = None,
        phone_number: Optional[str] = None,
        session_string: Optional[str] = None,
        order_queue: Optional[asyncio.Queue] = None,
    ):
        if not TELETHON_AVAILABLE:
            raise ImportError("Telethon is not installed. Run: pip install telethon")
        
        self.api_id = api_id or os.getenv('TELEGRAM_API_ID')
        self.api_hash = api_hash or os.getenv('TELEGRAM_API_HASH')
        self.phone_number = phone_number or os.getenv('TELEGRAM_PHONE')
        self.session_string = session_string
        
        self.order_queue: Optional[asyncio.Queue] = order_queue
        self.order_queue_loop: Optional[asyncio.AbstractEventLoop] = None
        self.sync_signal_queue: Optional[queue.Queue] = None
        
        self.client: Optional[TelegramClient] = None
        self.running = False
        self.connected = False
        
        self._monitored_chats: Set[Union[int, str]] = set()  # Can be int ID or @username
        self._chat_configs: Dict[Union[int, str], Dict[str, Any]] = {}
        self._username_to_id: Dict[str, int] = {}  # Cache @username -> numeric ID
        self._signal_callback: Optional[Callable] = None
        self._message_callback: Optional[Callable] = None
        
        self._db = None
        self._parsers: Dict[str, Callable] = {}
        
    def set_order_queue(self, async_queue: asyncio.Queue, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Set the asyncio order queue and its event loop for cross-thread signal submission."""
        self.order_queue = async_queue
        self.order_queue_loop = loop
        print(f"[TELEGRAM] Async order queue connected (loop: {loop is not None})")
    
    def set_sync_signal_queue(self, sync_queue: queue.Queue) -> None:
        """Set a thread-safe sync queue for signal submission (alternative to async queue)."""
        self.sync_signal_queue = sync_queue
        print(f"[TELEGRAM] Sync signal queue connected")
    
    def set_signal_callback(self, callback: Callable) -> None:
        """Set callback for when signals are parsed."""
        self._signal_callback = callback
        
    def set_message_callback(self, callback: Callable) -> None:
        """Set callback for all messages (for logging/tracking)."""
        self._message_callback = callback
    
    def register_parser(self, name: str, parser: Callable) -> None:
        """Register a signal parser function."""
        self._parsers[name] = parser
        print(f"[TELEGRAM] Registered parser: {name}")
    
    def add_monitored_chat(self, chat_id: Union[int, str], config: Optional[Dict[str, Any]] = None) -> None:
        """Add a chat to monitor for signals. Accepts int ID or @username string."""
        self._monitored_chats.add(chat_id)
        if config:
            self._chat_configs[chat_id] = config
        print(f"[TELEGRAM] Monitoring chat: {chat_id}")
    
    def remove_monitored_chat(self, chat_id: Union[int, str]) -> None:
        """Remove a chat from monitoring."""
        self._monitored_chats.discard(chat_id)
        self._chat_configs.pop(chat_id, None)
        print(f"[TELEGRAM] Removed chat from monitoring: {chat_id}")
    
    def _is_chat_monitored(self, chat_id: int, username: Optional[str] = None) -> Tuple[bool, Union[int, str, None]]:
        """Check if a chat is being monitored. Returns (is_monitored, config_key)."""
        # Normalize the incoming chat_id (strip -100 prefix if present)
        normalized_incoming = _normalize_chat_id(chat_id)
        
        # Check by exact numeric ID first
        if chat_id in self._monitored_chats:
            return True, chat_id
        
        # Check by normalized ID (handles -100 prefix mismatch)
        for monitored in self._monitored_chats:
            if isinstance(monitored, (int, str)) and not str(monitored).startswith('@'):
                normalized_monitored = _normalize_chat_id(monitored)
                if normalized_incoming == normalized_monitored:
                    _print_flush(f"[TELEGRAM] Matched chat {chat_id} to stored ID {monitored} (normalized: {normalized_incoming})")
                    return True, monitored
        
        # Check by @username
        if username:
            username_key = f"@{username}" if not username.startswith('@') else username
            if username_key in self._monitored_chats:
                # Cache the mapping for future lookups
                self._username_to_id[username_key] = chat_id
                return True, username_key
        
        # Check cached username-to-id mappings
        for uname, cached_id in self._username_to_id.items():
            if cached_id == chat_id and uname in self._monitored_chats:
                return True, uname
        
        return False, None
    
    def load_channels_from_db(self) -> int:
        """Load Telegram channels from database."""
        try:
            from gui_app.database import get_telegram_channels
            channels = get_telegram_channels()
            
            count = 0
            for channel in channels:
                chat_id_str = channel.get('telegram_chat_id')
                username = channel.get('telegram_username')
                
                if chat_id_str:
                    # Check if it's a @username or numeric ID
                    if chat_id_str.startswith('@'):
                        # It's a username, use it directly
                        self.add_monitored_chat(chat_id_str, config=channel)
                        count += 1
                    else:
                        try:
                            chat_id = int(chat_id_str)
                            self.add_monitored_chat(chat_id, config=channel)
                            count += 1
                        except (ValueError, TypeError):
                            # Maybe it's a username without @, add it
                            if chat_id_str:
                                self.add_monitored_chat(f"@{chat_id_str}", config=channel)
                                count += 1
                elif username:
                    # Use username if chat_id not provided
                    username_key = f"@{username}" if not username.startswith('@') else username
                    self.add_monitored_chat(username_key, config=channel)
                    count += 1
            
            print(f"[TELEGRAM] Loaded {count} channels from database")
            return count
        except Exception as e:
            print(f"[TELEGRAM] Error loading channels from database: {e}")
            return 0
    
    def reload_channels_from_db(self) -> int:
        """Reload Telegram channel configs from database (called when settings change via UI)."""
        self._monitored_chats.clear()
        self._chat_configs.clear()
        count = self.load_channels_from_db()
        print(f"[TELEGRAM] Reloaded {count} channel configs from database")
        return count
    
    async def connect(self) -> bool:
        """Connect to Telegram."""
        print(f"[TELEGRAM] connect() called - api_id={self.api_id}, has_hash={bool(self.api_hash)}, has_session={bool(self.session_string)}")
        if not self.api_id or not self.api_hash:
            print("[TELEGRAM] API credentials not configured")
            return False
        
        try:
            if self.session_string:
                session = StringSession(self.session_string)
                print("[TELEGRAM] Using existing session string")
            else:
                session = StringSession()
                print("[TELEGRAM] No session string - will need authorization")
            
            self.client = TelegramClient(
                session,
                int(self.api_id),
                self.api_hash,
                system_version="4.16.30-vxBotify"
            )
            
            print("[TELEGRAM] Connecting to Telegram servers...")
            await self.client.connect()
            print("[TELEGRAM] Connected to Telegram, checking authorization...")
            
            if not await self.client.is_user_authorized():
                if self.phone_number:
                    print(f"[TELEGRAM] Requesting verification code for {self.phone_number}")
                    await self.client.send_code_request(self.phone_number)
                    print("[TELEGRAM] Verification code sent. Use /api/telegram/verify to complete auth.")
                    return False
                else:
                    print("[TELEGRAM] Not authorized and no phone number provided")
                    return False
            
            me = await self.client.get_me()
            print(f"[TELEGRAM] Connected as: {me.first_name} (@{me.username or 'no username'})")
            
            self.connected = True
            
            if not self.session_string:
                new_session = self.client.session.save()
                await self._save_session_string(new_session)
            
            return True
            
        except Exception as e:
            print(f"[TELEGRAM] Connection error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def _save_session_string(self, session_string: str) -> None:
        """Save session string to database."""
        try:
            from gui_app.database import update_telegram_settings
            update_telegram_settings(session_string=session_string, session_status='connected')
            print("[TELEGRAM] Session string saved to database")
        except Exception as e:
            print(f"[TELEGRAM] Could not save session string: {e}")
    
    async def start_listening(self) -> None:
        """Start listening for messages in monitored chats."""
        if not self.client or not self.connected:
            print("[TELEGRAM] Not connected - call connect() first")
            return
        
        @self.client.on(events.NewMessage())
        async def message_handler(event: events.NewMessage.Event):
            await self._handle_message(event)
        
        self.running = True
        print(f"[TELEGRAM] Listening for signals in {len(self._monitored_chats)} chat(s)")
        
        await self.client.run_until_disconnected()
    
    async def _handle_message(self, event: events.NewMessage.Event) -> None:
        """Handle incoming Telegram message."""
        try:
            message = event.message
            chat = await event.get_chat()
            sender = await event.get_sender()
            
            chat_id = event.chat_id
            chat_username = getattr(chat, 'username', None)
            chat_title = getattr(chat, 'title', None) or chat_username or str(chat_id)
            content = message.text or ''
            
            # Debug: Log all incoming messages
            _print_flush(f"[TELEGRAM MSG] Chat: {chat_title} (ID: {chat_id}) | Text: {content[:100]}")
            
            # Check if this chat is monitored (by ID or @username)
            is_monitored, config_key = self._is_chat_monitored(chat_id, chat_username)
            if self._monitored_chats and not is_monitored:
                _print_flush(f"[TELEGRAM] Skipping - chat {chat_id} not in monitored list: {self._monitored_chats}")
                return
            
            chat_name = getattr(chat, 'title', None) or chat_username or str(chat_id)
            chat_type = self._get_chat_type(chat)
            
            author_id = sender.id if sender else 0
            author_name = self._get_sender_name(sender)
            
            content = message.text or ''
            
            normalized_msg = TelegramMessage(
                content=content,
                chat_id=chat_id,
                chat_name=chat_name,
                chat_type=chat_type,
                author_id=author_id,
                author_name=author_name,
                timestamp=message.date,
                message_id=message.id,
                raw_message=message,
            )
            
            if self._message_callback:
                try:
                    await self._message_callback(normalized_msg)
                except Exception as e:
                    print(f"[TELEGRAM] Message callback error: {e}")
            
            await self._process_signal(normalized_msg, config_key)
            
        except Exception as e:
            print(f"[TELEGRAM] Error handling message: {e}")
            import traceback
            traceback.print_exc()
    
    def _get_chat_type(self, chat: Any) -> str:
        """Determine chat type from Telethon entity."""
        if hasattr(chat, 'broadcast') and chat.broadcast:
            return 'channel'
        elif hasattr(chat, 'megagroup') and chat.megagroup:
            return 'supergroup'
        elif hasattr(chat, 'title'):
            return 'group'
        else:
            return 'private'
    
    def _get_sender_name(self, sender: Any) -> str:
        """Get sender display name."""
        if not sender:
            return 'Unknown'
        
        if hasattr(sender, 'first_name'):
            name = sender.first_name or ''
            if hasattr(sender, 'last_name') and sender.last_name:
                name += f' {sender.last_name}'
            return name.strip() or getattr(sender, 'username', 'Unknown') or 'Unknown'
        elif hasattr(sender, 'title'):
            return sender.title
        else:
            return 'Unknown'
    
    async def _process_signal(self, msg: TelegramMessage, config_key: Union[int, str, None] = None) -> None:
        """Process message through signal parsers."""
        if not msg.content.strip():
            return
        
        # Try config_key first (could be @username), then fall back to numeric ID
        chat_config = self._chat_configs.get(config_key, {}) if config_key else {}
        if not chat_config:
            chat_config = self._chat_configs.get(msg.chat_id, {})
        
        execute_enabled = chat_config.get('execute_enabled', 0)
        track_enabled = chat_config.get('track_enabled', 0)
        
        if not execute_enabled and not track_enabled:
            print(f"[TELEGRAM] ⚠️ Channel {msg.chat_id} not configured for execution/tracking (config_key={config_key}, execute={execute_enabled}, track={track_enabled})")
            return
        
        print(f"[TELEGRAM] ✓ Processing signal from {msg.chat_name} (execute={execute_enabled}, track={track_enabled})")
        
        signal = None

        # Priority 1: SignalFormatRegistry (50+ patterns — same as Discord)
        try:
            from src.services.signal_format_registry import get_registry
            registry = get_registry()
            if registry:
                reg_results = registry.parse_all_with_registry(msg.content)
                if reg_results:
                    signal = reg_results[0]
                    _print_flush(f"[TELEGRAM] ✓ FORMAT REGISTRY match: {signal.get('_format_name', '?')} → {signal.get('action', '')} {signal.get('symbol', '')}")
        except Exception as e:
            _print_flush(f"[TELEGRAM] Registry parse error (falling back): {e}")

        # Priority 2: Base parsers (4 registered — stock/option US/India)
        if not signal:
            for parser_name, parser_func in self._parsers.items():
                try:
                    result = parser_func(msg.content)
                    if result:
                        signal = result
                        _print_flush(f"[TELEGRAM] Signal parsed by {parser_name}: {result.get('action', '')} {result.get('symbol', '')}")
                        break
                except Exception as e:
                    _print_flush(f"[TELEGRAM] Parser {parser_name} error: {e}")

        # Priority 3: AI Fallback (same as Discord AI_FALLBACK path)
        if not signal:
            try:
                from src.services.ai_signal_parser import parse_signal_with_ai
                ai_result = parse_signal_with_ai(msg.content)
                if ai_result and ai_result.get('confidence', 0) >= 0.80:
                    signal = ai_result
                    signal['_ai_fallback'] = True
                    _print_flush(f"[TELEGRAM] [AI_FALLBACK] ✓ AI parsed: {ai_result.get('action', '')} {ai_result.get('symbol', '')} (confidence={ai_result.get('confidence', 0):.2f})")

                    # Auto-learn: store format candidate for Dashboard approval
                    try:
                        from gui_app.database import get_trading_settings, save_ai_format_candidate
                        _auto_learn = get_trading_settings().get('ai_auto_learn_enabled', '1') != '0'
                        if _auto_learn:
                            save_ai_format_candidate(
                                channel_id=str(msg.chat_id),
                                channel_name=msg.chat_name or '',
                                original_text=str(msg.content),
                                ai_result=ai_result,
                                confidence=ai_result.get('confidence', 0),
                            )
                    except Exception as _learn_err:
                        _print_flush(f"[TELEGRAM] [AI_FALLBACK] ⚠️ Auto-learn error: {_learn_err}")
                elif ai_result:
                    _print_flush(f"[TELEGRAM] [AI_FALLBACK] ⚠️ Low confidence ({ai_result.get('confidence', 0):.2f}) — not executing: {ai_result.get('action', '')} {ai_result.get('symbol', '')}")
            except Exception as e:
                _print_flush(f"[TELEGRAM] AI fallback error: {e}")

        if signal:
            from datetime import datetime as _dt
            signal['detected_at'] = _dt.now().isoformat()
            signal['parsed_at'] = _dt.now().isoformat()
            signal['platform'] = 'telegram'
            signal['channel_id'] = str(msg.chat_id)
            signal['channel_name'] = msg.chat_name
            signal['author_name'] = msg.author_name
            signal['timestamp'] = msg.timestamp.isoformat()
            signal['_db_channel_id'] = chat_config.get('id')
            signal['message_id'] = str(msg.message_id)

            # Broker override
            broker_override = chat_config.get('broker_override')
            if broker_override:
                signal['_broker_override'] = broker_override

            enabled_brokers = chat_config.get('enabled_brokers')
            if enabled_brokers:
                import json
                try:
                    signal['_enabled_brokers'] = json.loads(enabled_brokers) if isinstance(enabled_brokers, str) else enabled_brokers
                except Exception:
                    pass

            # ── Channel Sizing (full cascade matching Discord) ──
            default_qty = chat_config.get('default_quantity')
            position_size_pct = chat_config.get('position_size_pct')
            channel_max = chat_config.get('channel_max_position_size')
            has_explicit_qty = signal.get('_qty_from_signal') or signal.get('qty') or signal.get('lots')

            if default_qty and int(default_qty) > 0:
                if not has_explicit_qty:
                    signal['qty'] = int(default_qty)
                else:
                    signal['qty'] = min(int(signal.get('qty', default_qty)), int(default_qty))
                signal['_used_default_qty'] = True
                signal['_qty_source'] = 'channel_default'
                print(f"[TELEGRAM] [POSITION SIZE] ✓ Channel default_qty={default_qty}")
            elif position_size_pct:
                signal['_position_size_pct'] = float(position_size_pct)
                signal['_pct_from_channel'] = True
                signal['_calculate_qty'] = True
                print(f"[TELEGRAM] [POSITION SIZE] ✓ Channel position_size_pct={position_size_pct}%")

            # Channel max position size cap
            if channel_max and signal.get('action', '').upper() in ('BTO', 'BUY'):
                signal['_channel_max_position_size'] = float(channel_max)
                _sig_price = signal.get('price') or signal.get('limit_price') or 0
                _sig_qty = signal.get('qty', 1)
                _mult = 100 if signal.get('asset') == 'option' else 1
                if _sig_price and _sig_price > 0 and signal.get('_used_default_qty'):
                    _cost = _sig_price * _mult * _sig_qty
                    if _cost > float(channel_max):
                        _capped = max(1, int(float(channel_max) / (_sig_price * _mult)))
                        print(f"[TELEGRAM] [MAX POS$] ⚠️ Capped: {_sig_qty} → {_capped} (${_cost:.0f} > max ${float(channel_max):.0f})")
                        signal['qty'] = _capped

            # ── Channel Risk Config (matching Discord _channel_risk_config) ──
            _risk_fields = {}
            for _rk in ('stop_loss_pct', 'profit_target_1_pct', 'profit_target_2_pct', 'profit_target_3_pct',
                         'profit_target_4_pct', 'trailing_stop_pct', 'trailing_activation_pct',
                         'exit_strategy_mode', 'broker_bracket_mode', 'enable_dynamic_sl',
                         'dynamic_sl_profile', 'enable_early_trailing', 'early_trailing_activation_pct',
                         'early_trailing_step_pct', 'enable_giveback_guard', 'giveback_allowed_pct',
                         'profit_target_qty_1', 'profit_target_qty_2', 'profit_target_qty_3', 'profit_target_qty_4'):
                _rv = chat_config.get(_rk)
                if _rv is not None:
                    _risk_fields[_rk] = _rv
            if _risk_fields:
                signal['_channel_risk_config'] = _risk_fields

            exit_mode = chat_config.get('exit_strategy_mode')
            if exit_mode:
                signal['_exit_strategy_mode'] = exit_mode

            # ── Conditional order detection (US + India) ──
            if signal.get('_conditional_order') or signal.get('is_conditional'):
                signal['_conditional_order'] = True
                print(f"[TELEGRAM] ✓ Conditional order detected: {signal.get('trigger_type', 'over')} {signal.get('trigger_price', signal.get('price', '?'))}")

            # ── Entry confirmation % routing ──
            entry_confirm_pct = chat_config.get('entry_confirmation_pct')
            if entry_confirm_pct and float(entry_confirm_pct) > 0 and signal.get('action', '').upper() == 'BTO':
                _asset = signal.get('asset', signal.get('asset_type', ''))
                if _asset != 'option':  # stocks only
                    _entry_price = signal.get('price') or signal.get('limit_price')
                    if _entry_price and float(_entry_price) > 0:
                        signal['_conditional_order'] = True
                        signal['trigger_price'] = float(_entry_price) * (1 + float(entry_confirm_pct) / 100)
                        signal['trigger_type'] = 'over'
                        print(f"[TELEGRAM] ✓ Entry confirmation: {entry_confirm_pct}% → trigger at ${signal['trigger_price']:.2f}")

            # ── Save for tracking ──
            if track_enabled:
                try:
                    self._save_signal_for_tracking(signal, msg)
                except Exception as e:
                    print(f"[TELEGRAM] Error saving signal for tracking: {e}")

            # ── Queue for execution ──
            if execute_enabled:
                _tg_action = signal.get('action', '').upper()
                _tg_exit_mode = signal.get('_exit_strategy_mode', 'signal')
                if _tg_action in ('STC', 'SELL') and _tg_exit_mode == 'risk':
                    print(f"[EXIT MODE] ⛔ BLOCKED: Telegram STC for {signal.get('symbol')} — exit_strategy_mode='risk'")
                else:
                    queued = await self._submit_signal_to_queue(signal)
                    if queued:
                        print(f"[TELEGRAM] ✓ Signal queued for execution")

            if self._signal_callback:
                try:
                    await self._signal_callback(signal, msg)
                except Exception as e:
                    print(f"[TELEGRAM] Signal callback error: {e}")
    
    def _save_signal_for_tracking(self, signal: Dict[str, Any], msg: TelegramMessage) -> None:
        """Save signal to database for PNL tracking."""
        try:
            from gui_app.database import add_signal, create_signal_lot, get_connection, get_open_lots, close_lot
            from datetime import datetime
            
            action = signal.get('action', 'BTO')
            symbol = signal.get('symbol', '')
            market = signal.get('market', 'US')
            
            if market == 'INDIA':
                quantity = signal.get('lots') or signal.get('qty') or 1
            else:
                quantity = signal.get('qty') or signal.get('quantity') or 1
            
            price = signal.get('price') or 0
            asset_type = signal.get('asset_type', 'option')
            strike = signal.get('strike')
            expiry = signal.get('expiry')
            call_put = signal.get('option_type') or signal.get('call_put')
            author_name = signal.get('author_name', msg.author_name)
            channel_id = signal.get('channel_id', str(msg.chat_id))
            
            signal_id = add_signal(
                discord_channel_id=channel_id,
                message_id=str(msg.message_id),
                signal_type=action,
                symbol=symbol,
                quantity=quantity,
                price=price,
                asset_type=asset_type,
                author_name=author_name,
                strike=strike,
                expiry=expiry,
                call_put=call_put,
                market=market
            )
            
            if signal_id:
                print(f"[TELEGRAM] ✓ Signal saved for tracking (ID: {signal_id}, Market: {market})")
                
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT id FROM channels WHERE telegram_chat_id = ?', (channel_id,))
                channel = cursor.fetchone()
                db_channel_id = channel['id'] if channel else None
                
                if action == 'BTO':
                    if db_channel_id:
                        lot_id = create_signal_lot(
                            channel_id=db_channel_id,
                            signal_id=signal_id,
                            asset_type=asset_type,
                            symbol=symbol,
                            quantity=quantity,
                            open_price=price,
                            opened_at=datetime.now().isoformat(),
                            strike=strike,
                            expiry=expiry,
                            call_put=call_put,
                            author_name=author_name
                        )
                        print(f"[TELEGRAM] ✓ Signal lot created for PNL tracking (Lot ID: {lot_id})")
                    else:
                        print(f"[TELEGRAM] ⚠️ Channel not found in DB for lot creation: {channel_id}")
                
                elif action == 'STC':
                    if db_channel_id:
                        open_lots = get_open_lots(
                            channel_id=db_channel_id,
                            asset_type=asset_type,
                            symbol=symbol,
                            strike=strike,
                            expiry=expiry,
                            call_put=call_put
                        )
                        
                        if open_lots:
                            lot = open_lots[0]
                            close_qty = min(quantity, lot['remaining_qty'])
                            closure_id = close_lot(
                                lot_id=lot['id'],
                                channel_id=db_channel_id,
                                signal_id=signal_id,
                                close_qty=close_qty,
                                close_price=price,
                                closed_at=datetime.now().isoformat()
                            )
                            
                            open_price = lot['open_price']
                            pnl = (price - open_price) * close_qty
                            if asset_type == 'option' and market == 'US':
                                pnl *= 100
                            
                            print(f"[TELEGRAM] ✓ Lot closed for PNL tracking (Closure ID: {closure_id}, PNL: {'+' if pnl >= 0 else ''}{pnl:.2f})")
                        else:
                            print(f"[TELEGRAM] ⚠️ No matching open lot found for STC: {symbol} {strike} {call_put}")
                    else:
                        print(f"[TELEGRAM] ⚠️ Channel not found in DB for lot closure: {channel_id}")
            else:
                print(f"[TELEGRAM] ⚠️ Failed to save signal for tracking")
                
        except Exception as e:
            print(f"[TELEGRAM] Error in _save_signal_for_tracking: {e}")
            import traceback
            traceback.print_exc()

    async def _submit_signal_to_queue(self, signal: Dict[str, Any]) -> bool:
        """
        Submit signal to the order queue in a thread-safe manner.
        Handles cross-loop asyncio queue submission using run_coroutine_threadsafe.
        """
        try:
            if self.sync_signal_queue is not None:
                self.sync_signal_queue.put_nowait(signal)
                return True
            
            if self.order_queue is not None and self.order_queue_loop is not None:
                future = asyncio.run_coroutine_threadsafe(
                    self.order_queue.put(signal),
                    self.order_queue_loop
                )
                future.result(timeout=5.0)
                return True
            
            if self.order_queue is not None:
                try:
                    self.order_queue.put_nowait(signal)
                    return True
                except Exception as e:
                    print(f"[TELEGRAM] Direct queue put failed (cross-loop issue): {e}")
                    return False
            
            return False
            
        except Exception as e:
            print(f"[TELEGRAM] Error submitting signal to queue: {e}")
            return False
    
    async def disconnect(self) -> None:
        """Disconnect from Telegram."""
        self.running = False
        if self.client:
            await self.client.disconnect()
            print("[TELEGRAM] Disconnected")
        self.connected = False
    
    def is_connected(self) -> bool:
        """Check if connected to Telegram."""
        return self.connected and self.client is not None
    
    def get_status(self) -> Dict[str, Any]:
        """Get current listener status."""
        return {
            'connected': self.connected,
            'running': self.running,
            'monitored_chats': len(self._monitored_chats),
            'parsers': list(self._parsers.keys()),
            'has_queue': self.order_queue is not None,
        }


_telegram_listener: Optional[TelegramListener] = None


def get_telegram_listener() -> Optional[TelegramListener]:
    """Get the global TelegramListener instance."""
    return _telegram_listener


def set_telegram_listener(listener: TelegramListener) -> None:
    """Set the global TelegramListener instance."""
    global _telegram_listener
    _telegram_listener = listener


async def start_telegram_listener(
    api_id: str,
    api_hash: str,
    phone_number: Optional[str] = None,
    session_string: Optional[str] = None,
    order_queue: Optional[asyncio.Queue] = None,
) -> Optional[TelegramListener]:
    """
    Create and start the Telegram listener.
    
    This is the main entry point for initializing Telegram integration.
    """
    if not TELETHON_AVAILABLE:
        print("[TELEGRAM] Telethon not installed - Telegram integration disabled")
        return None
    
    try:
        listener = TelegramListener(
            api_id=api_id,
            api_hash=api_hash,
            phone_number=phone_number,
            session_string=session_string,
            order_queue=order_queue,
        )
        
        listener.load_channels_from_db()
        
        connected = await listener.connect()
        if not connected:
            print("[TELEGRAM] Could not connect - check credentials")
            return listener
        
        set_telegram_listener(listener)
        
        return listener
        
    except Exception as e:
        print(f"[TELEGRAM] Failed to start listener: {e}")
        import traceback
        traceback.print_exc()
        return None
