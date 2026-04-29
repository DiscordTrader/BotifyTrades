"""
Unified Signal Parsing Pipeline
================================
Industry-grade signal parsing with dedupe, priority, confidence scoring.
Used by both Signal Routing and Broker Execution paths.

Features:
- Tiered parsing: Embeds → Registry → Trader-specific → Standard → AI Fallback
- Dedupe with TTL to prevent duplicate processing
- Confidence scoring (regex=1.0, AI=variable)
- Normalized output schema
- Stock and options support
"""

import re
import hashlib
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from enum import Enum


class SignalSource(Enum):
    EMBED_SPY_SNIPER = "spy_sniper"
    EMBED_SIR_GOLDMAN = "sir_goldman"
    EMBED_HENGY = "hengy_alerts"
    EMBED_KC_TRADES = "kc_trades"
    REGISTRY_JAKE = "jake"
    REGISTRY_SLEM = "slem"
    REGISTRY_STACK = "stack"
    REGISTRY_FOXTRADES = "foxtrades"
    REGISTRY_TEMPLE = "temple"
    REGISTRY_LEARNED = "learned_pattern"
    TRADER_BISHOP = "bishop"
    TRADER_EVAPANDA = "evapanda"
    TRADER_BULLWINKLE = "bullwinkle"
    TRADER_JACOB = "jacob"
    TRADER_ZSCALPS = "zscalps"
    TRADER_JAKE = "jake_trader"
    STANDARD_BTO_STC = "standard"
    AI_FALLBACK = "ai_fallback"
    UNKNOWN = "unknown"


@dataclass
class ParsedSignal:
    """Normalized signal output from parsing pipeline."""
    action: str  # BTO, STC, TRIM, UPDATE
    asset: str  # option, stock
    symbol: str
    strike: Optional[float] = None
    expiry: Optional[str] = None
    option_type: Optional[str] = None  # C or P
    price: Optional[float] = None
    qty: int = 1
    confidence: float = 1.0  # 1.0 for regex, variable for AI
    source: SignalSource = SignalSource.UNKNOWN
    is_trim: bool = False
    is_full_exit: bool = True
    is_market_order: bool = False
    raw_text: str = ""
    message_id: str = ""
    channel_id: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    # Security flags for execution gating
    execution_allowed: bool = True  # False for AI/learned unless admin-approved
    requires_approval: bool = False  # True for AI/learned signals
    admin_approved: bool = False  # True if admin has approved this pattern/source
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'action': self.action,
            'asset': self.asset,
            'symbol': self.symbol,
            'strike': self.strike,
            'expiry': self.expiry,
            'opt_type': self.option_type,
            'price': self.price,
            'qty': self.qty,
            'confidence': self.confidence,
            'source': self.source.value,
            'is_trim': self.is_trim,
            'is_full_exit': self.is_full_exit,
            'is_market_order': self.is_market_order,
            'message_id': self.message_id,
            'channel_id': self.channel_id,
            'execution_allowed': self.execution_allowed,
            'requires_approval': self.requires_approval,
            'admin_approved': self.admin_approved
        }
    
    def can_execute(self) -> bool:
        """Check if this signal can be executed (security gate)."""
        # AI/learned signals require admin approval for execution
        if self.source in (SignalSource.AI_FALLBACK, SignalSource.REGISTRY_LEARNED):
            return self.admin_approved and self.execution_allowed
        # All other sources can execute if confidence >= 0.8
        return self.execution_allowed and self.confidence >= 0.8
    
    def dedupe_key(self) -> str:
        """Generate unique key for deduplication."""
        key_parts = [
            self.channel_id,
            self.action,
            self.symbol,
            str(self.strike or ''),
            self.option_type or '',
            self.expiry or '',
            str(self.price or '')
        ]
        key_str = '|'.join(key_parts)
        return hashlib.md5(key_str.encode()).hexdigest()


class SignalDeduplicator:
    """Prevents duplicate signal processing with TTL."""
    
    def __init__(self, ttl_seconds: int = 300):
        self._seen: Dict[str, datetime] = {}
        self._ttl = timedelta(seconds=ttl_seconds)
        self._lock = asyncio.Lock()
    
    async def is_duplicate(self, signal: ParsedSignal) -> bool:
        """Check if signal was recently processed."""
        async with self._lock:
            self._cleanup_expired()
            key = signal.dedupe_key()
            if key in self._seen:
                print(f"[DEDUPE] ⛔ Duplicate signal detected: {signal.symbol} {signal.action}")
                return True
            return False
    
    async def mark_processed(self, signal: ParsedSignal) -> None:
        """Mark signal as processed."""
        async with self._lock:
            key = signal.dedupe_key()
            self._seen[key] = datetime.now()
    
    def _cleanup_expired(self) -> None:
        """Remove expired entries."""
        now = datetime.now()
        expired = [k for k, v in self._seen.items() if now - v > self._ttl]
        for k in expired:
            del self._seen[k]


class SignalParsingPipeline:
    """
    Unified signal parsing pipeline with tiered priority.
    
    Priority Order:
    1. Embed parsers (Spy-Sniper, Sir Goldman)
    2. SignalFormatRegistry (Jake, Slem, STACK$, Foxtrades, Learned)
    3. Trader-specific parsers (Bishop, EvaPanda, etc.)
    4. Standard BTO/STC regex
    5. AI Fallback (async, confidence-gated)
    """
    
    def __init__(self):
        self._deduplicator = SignalDeduplicator(ttl_seconds=300)
        self._ai_enabled = False
        self._ai_min_confidence = 0.8
        self._ai_execution_allowed = False  # Security: AI cannot execute by default
    
    async def parse(
        self,
        text: str,
        embeds: Optional[List[Dict]] = None,
        message_id: str = "",
        channel_id: str = "",
        check_dedupe: bool = True
    ) -> Optional[ParsedSignal]:
        """
        Parse signal through tiered pipeline.
        
        Args:
            text: Message content
            embeds: List of embed dicts with 'title' and 'description'
            message_id: Discord message ID
            channel_id: Discord channel ID
            check_dedupe: Whether to check for duplicates
            
        Returns:
            ParsedSignal if detected, None otherwise
        """
        result = None
        
        # TIER 1: Embed parsers (highest priority)
        if embeds:
            result = self._parse_embeds(embeds, message_id, channel_id)
            if result:
                print(f"[PIPELINE] ✓ Tier 1 (Embed): {result.source.value} - {result.action} {result.symbol}")
        
        # TIER 2: SignalFormatRegistry
        if not result:
            result = self._parse_registry(text, message_id, channel_id)
            if result:
                print(f"[PIPELINE] ✓ Tier 2 (Registry): {result.source.value} - {result.action} {result.symbol}")
        
        # TIER 3: Trader-specific parsers
        if not result:
            result = self._parse_trader_specific(text, message_id, channel_id)
            if result:
                print(f"[PIPELINE] ✓ Tier 3 (Trader): {result.source.value} - {result.action} {result.symbol}")
        
        # TIER 4: Standard BTO/STC regex
        if not result:
            result = self._parse_standard(text, message_id, channel_id)
            if result:
                print(f"[PIPELINE] ✓ Tier 4 (Standard): {result.action} {result.symbol}")
        
        # TIER 5: AI Fallback (only if enabled and contains potential ticker)
        if not result and self._ai_enabled and self._contains_ticker(text):
            result = await self._parse_ai_fallback(text, message_id, channel_id)
            if result:
                print(f"[PIPELINE] ✓ Tier 5 (AI): confidence={result.confidence:.2f} - {result.action} {result.symbol}")
                if result.confidence < self._ai_min_confidence:
                    print(f"[PIPELINE] ⚠️ AI confidence too low ({result.confidence:.2f} < {self._ai_min_confidence})")
                    result = None
        
        # SECURITY GATE: Block AI/learned signals that aren't approved for execution
        if result and result.requires_approval and not result.admin_approved:
            print(f"[PIPELINE] ⛔ SECURITY: {result.source.value} signal blocked - requires admin approval")
            print(f"[PIPELINE]    Symbol: {result.symbol}, Action: {result.action}")
            print(f"[PIPELINE]    execution_allowed={result.execution_allowed}, can_execute={result.can_execute()}")
            # Return None to prevent any downstream execution
            return None
        
        # Confidence gate: Block low-confidence signals
        if result and not result.can_execute():
            print(f"[PIPELINE] ⛔ SECURITY: Signal blocked - confidence too low or not allowed")
            print(f"[PIPELINE]    confidence={result.confidence:.2f}, execution_allowed={result.execution_allowed}")
            return None
        
        # Dedupe check
        if result and check_dedupe:
            if await self._deduplicator.is_duplicate(result):
                return None
            await self._deduplicator.mark_processed(result)
        
        return result
    
    def _parse_embeds(self, embeds: List[Dict], message_id: str, channel_id: str) -> Optional[ParsedSignal]:
        """Parse embed-based signals (Spy-Sniper, Sir Goldman)."""
        for embed in embeds:
            title = embed.get('title', '') or ''
            description = embed.get('description', '') or ''
            
            # Sir Goldman detection
            if any(kw in title.upper() for kw in ['ENTRY', 'EXIT', 'TRIM']):
                try:
                    from src.signals.sir_goldman_parser import parse_sir_goldman_signal
                    embeds_list = [embed]
                    sg_signal = parse_sir_goldman_signal(embeds_list)
                    if sg_signal:
                        return ParsedSignal(
                            action=sg_signal.action,
                            asset='option',
                            symbol=sg_signal.symbol,
                            strike=sg_signal.strike,
                            option_type=sg_signal.option_type,
                            price=sg_signal.price,
                            confidence=1.0,
                            source=SignalSource.EMBED_SIR_GOLDMAN,
                            is_trim=sg_signal.signal_type.value == 'TRIM',
                            is_market_order=sg_signal.is_market_exit,
                            message_id=message_id,
                            channel_id=channel_id
                        )
                except Exception as e:
                    print(f"[PIPELINE] Sir Goldman parse error: {e}")
            
            # Spy-Sniper detection
            if 'ALERT' in title.upper() or 'OPEN' in title.upper() or 'CLOSE' in title.upper():
                try:
                    from src.signals.spy_sniper_parser import parse_spy_sniper_signal, SpySniperSignalType
                    spy_signal = parse_spy_sniper_signal(title, description, message_id)
                    if spy_signal:
                        action = 'BTO' if spy_signal.signal_type == SpySniperSignalType.ENTRY else 'STC'
                        return ParsedSignal(
                            action=action,
                            asset='option',
                            symbol=spy_signal.symbol,
                            strike=spy_signal.strike,
                            option_type=spy_signal.option_type,
                            expiry=spy_signal.expiry_date,
                            price=spy_signal.entry_price if action == 'BTO' else spy_signal.current_price,
                            confidence=1.0,
                            source=SignalSource.EMBED_SPY_SNIPER,
                            is_full_exit=spy_signal.is_full_exit if hasattr(spy_signal, 'is_full_exit') else True,
                            message_id=message_id,
                            channel_id=channel_id
                        )
                except Exception as e:
                    print(f"[PIPELINE] Spy-Sniper parse error: {e}")
            
            # Hengy Alerts detection (breakout watchlist signals)
            if 'TRADE' in title.upper() and ('IDEA' in title.upper() or 'UPDATE' in title.upper()):
                try:
                    from src.signals.hengy_parser import is_hengy_embed, parse_hengy_embed
                    if is_hengy_embed(title, description):
                        parsed_list = parse_hengy_embed(title, description)
                        if parsed_list:
                            first = parsed_list[0]
                            return ParsedSignal(
                                action='BTO',
                                asset='stock',
                                symbol=first['symbol'],
                                price=first.get('trigger_price'),
                                confidence=1.0,
                                source=SignalSource.EMBED_HENGY,
                                message_id=message_id,
                                channel_id=channel_id,
                                raw_text=first.get('_original_message', '')
                            )
                except Exception as e:
                    print(f"[PIPELINE] Hengy parse error: {e}")
        
        return None
    
    def _parse_registry(self, text: str, message_id: str, channel_id: str) -> Optional[ParsedSignal]:
        """Parse using SignalFormatRegistry (includes Foxtrades, learned patterns)."""
        try:
            from src.services.signal_format_registry import parse_with_registry
            result = parse_with_registry(text)
            if result and result.get('action') in ['BTO', 'STC']:
                # Security: Check for learned pattern flags
                is_learned = result.get('_learned_pattern', False)
                admin_approved = result.get('_admin_approved', False)
                requires_approval = result.get('_requires_approval', False)
                
                return ParsedSignal(
                    action=result['action'],
                    asset=result.get('asset', 'option'),
                    symbol=result.get('symbol', ''),
                    strike=result.get('strike'),
                    option_type=result.get('opt_type'),
                    expiry=result.get('expiry'),
                    price=result.get('price'),
                    qty=result.get('qty', 1),
                    confidence=result.get('confidence', 1.0),
                    source=SignalSource.REGISTRY_LEARNED if is_learned else self._map_registry_source(result.get('_format_name', '')),
                    # Security: Set execution gating for learned patterns
                    execution_allowed=result.get('_execution_allowed', not is_learned),
                    requires_approval=requires_approval or is_learned,
                    admin_approved=admin_approved,
                    message_id=message_id,
                    channel_id=channel_id
                )
        except Exception as e:
            print(f"[PIPELINE] Registry parse error: {e}")
        
        return None
    
    def _parse_trader_specific(self, text: str, message_id: str, channel_id: str) -> Optional[ParsedSignal]:
        """Parse trader-specific formats (Bishop, EvaPanda, etc.)."""
        text_upper = text.upper()
        
        # Bishop format
        if "I'M ENTERING" in text_upper or "TRIMMING" in text_upper:
            try:
                from src.selfbot_webull import parse_bishop_signal
                result = parse_bishop_signal(text)
                if result:
                    return self._convert_dict_to_signal(result, SignalSource.TRADER_BISHOP, message_id, channel_id)
            except Exception:
                pass
        
        # EvaPanda format
        if re.search(r'(BTO|STC)\s+[A-Z]+\s+\d+/\d+/\d+', text_upper):
            try:
                from src.selfbot_webull import parse_evapanda_signal
                result = parse_evapanda_signal(text)
                if result:
                    return self._convert_dict_to_signal(result, SignalSource.TRADER_EVAPANDA, message_id, channel_id)
            except Exception:
                pass
        
        return None
    
    def _parse_standard(self, text: str, message_id: str, channel_id: str) -> Optional[ParsedSignal]:
        """Parse standard BTO/STC format."""
        try:
            from src.selfbot_webull import parse_option_signal
            result = parse_option_signal(text)
            if result:
                return self._convert_dict_to_signal(result, SignalSource.STANDARD_BTO_STC, message_id, channel_id)
        except Exception as e:
            print(f"[PIPELINE] Standard parse error: {e}")
        
        return None
    
    async def _parse_ai_fallback(self, text: str, message_id: str, channel_id: str) -> Optional[ParsedSignal]:
        """AI-based parsing for unknown formats (async, confidence-gated)."""
        try:
            from src.services.ai_signal_parser import parse_signal_with_ai
            result = await parse_signal_with_ai(text)
            if result and result.get('action') and result.get('symbol'):
                confidence = result.get('confidence', 0.5)
                signal = ParsedSignal(
                    action=result['action'],
                    asset=result.get('asset', 'stock'),
                    symbol=result['symbol'],
                    strike=result.get('strike'),
                    option_type=result.get('option_type'),
                    price=result.get('price'),
                    qty=result.get('qty', 1),
                    confidence=confidence,
                    source=SignalSource.AI_FALLBACK,
                    message_id=message_id,
                    channel_id=channel_id,
                    # Security: AI signals cannot execute without admin approval
                    execution_allowed=self._ai_execution_allowed,
                    requires_approval=True,
                    admin_approved=False  # AI signals are never pre-approved
                )
                return signal
        except Exception as e:
            print(f"[PIPELINE] AI fallback error: {e}")
        
        return None
    
    def _contains_ticker(self, text: str) -> bool:
        """Check if text contains potential stock ticker."""
        ticker_pattern = r'\$[A-Z]{1,5}\b|\b[A-Z]{2,5}\b'
        return bool(re.search(ticker_pattern, text.upper()))
    
    def _map_registry_source(self, format_name: str) -> SignalSource:
        """Map registry format name to SignalSource."""
        mapping = {
            'jake': SignalSource.REGISTRY_JAKE,
            'slem': SignalSource.REGISTRY_SLEM,
            'stack': SignalSource.REGISTRY_STACK,
            'foxtrades': SignalSource.REGISTRY_FOXTRADES,
            'temple': SignalSource.REGISTRY_TEMPLE,
            'learned': SignalSource.REGISTRY_LEARNED
        }
        for key, source in mapping.items():
            if key in format_name.lower():
                return source
        return SignalSource.UNKNOWN
    
    def _convert_dict_to_signal(self, d: Dict, source: SignalSource, message_id: str, channel_id: str) -> ParsedSignal:
        """Convert parser dict to ParsedSignal."""
        return ParsedSignal(
            action=d.get('action', 'BTO'),
            asset=d.get('asset', 'option'),
            symbol=d.get('symbol', ''),
            strike=d.get('strike'),
            option_type=d.get('opt_type') or d.get('option_type'),
            expiry=d.get('expiry'),
            price=d.get('price'),
            qty=d.get('qty', 1),
            confidence=d.get('confidence', 1.0),
            source=source,
            is_trim=d.get('is_trim', False),
            is_market_order=d.get('is_market_order', False),
            message_id=message_id,
            channel_id=channel_id
        )
    
    def enable_ai_fallback(self, enabled: bool = True, min_confidence: float = 0.8, allow_execution: bool = False):
        """Configure AI fallback settings."""
        self._ai_enabled = enabled
        self._ai_min_confidence = min_confidence
        self._ai_execution_allowed = allow_execution
        print(f"[PIPELINE] AI fallback: enabled={enabled}, min_confidence={min_confidence}, execution={allow_execution}")


# Global singleton
_pipeline_instance: Optional[SignalParsingPipeline] = None


def get_signal_pipeline() -> SignalParsingPipeline:
    """Get global pipeline instance."""
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = SignalParsingPipeline()
    return _pipeline_instance


async def parse_signal(
    text: str,
    embeds: Optional[List[Dict]] = None,
    message_id: str = "",
    channel_id: str = ""
) -> Optional[ParsedSignal]:
    """Convenience function for parsing signals."""
    return await get_signal_pipeline().parse(text, embeds, message_id, channel_id)
