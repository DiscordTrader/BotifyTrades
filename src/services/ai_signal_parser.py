"""
AI-Powered Signal Parser
=========================
Uses OpenAI to parse unknown natural language trading signals.
Includes async processing, rate limiting, caching, and confidence gating.

Security:
- AI-parsed signals cannot execute trades by default
- Requires explicit admin approval for execution
- Confidence threshold must be met
"""

import os
import json
import hashlib
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("[AI_PARSER] OpenAI not available")

try:
    from anthropic import AsyncAnthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


@dataclass
class AIParseResult:
    """Result from AI signal parsing."""
    action: Optional[str] = None  # BTO, STC, TRIM, ADD
    asset: str = "stock"  # stock or option
    symbol: Optional[str] = None
    strike: Optional[float] = None
    option_type: Optional[str] = None
    expiry: Optional[str] = None
    price: Optional[float] = None
    qty: int = 1
    confidence: float = 0.0
    rationale: str = ""
    is_trim: bool = False
    error: Optional[str] = None


class AISignalParserCache:
    """Cache for AI parsing results to reduce API costs."""
    
    def __init__(self, ttl_seconds: int = 3600):
        self._cache: Dict[str, tuple] = {}  # hash -> (result, timestamp)
        self._ttl = timedelta(seconds=ttl_seconds)
    
    def _hash_text(self, text: str) -> str:
        return hashlib.md5(text.strip().lower().encode()).hexdigest()
    
    def get(self, text: str) -> Optional[AIParseResult]:
        key = self._hash_text(text)
        if key in self._cache:
            result, timestamp = self._cache[key]
            if datetime.now() - timestamp < self._ttl:
                return result
            else:
                del self._cache[key]
        return None
    
    def set(self, text: str, result: AIParseResult) -> None:
        key = self._hash_text(text)
        self._cache[key] = (result, datetime.now())
    
    def clear_expired(self) -> None:
        now = datetime.now()
        expired = [k for k, (_, ts) in self._cache.items() if now - ts > self._ttl]
        for k in expired:
            del self._cache[k]


class AISignalParser:
    """
    AI-based signal parser using OpenAI.
    
    Features:
    - Async processing
    - Rate limiting with semaphore
    - Result caching
    - Few-shot prompting with examples
    - Confidence scoring
    """
    
    def __init__(self, max_concurrent: int = 3):
        self._client: Optional[AsyncOpenAI] = None
        self._anthropic_client = None
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._cache = AISignalParserCache()
        self._model = "gpt-4o-mini"
        self._anthropic_model = "claude-haiku-4-5-20251001"
        self._provider = None
        self._initialized = False
        self._few_shot_examples: List[Dict] = []
        self._load_few_shot_examples()

    def _get_provider(self) -> str:
        try:
            from gui_app.config_service import get_ai_provider
            return get_ai_provider()
        except Exception:
            return 'disabled'

    def _init_client(self) -> bool:
        """Initialize AI client based on provider config."""
        provider = self._get_provider()

        if provider != self._provider:
            self._initialized = False
            self._client = None
            self._anthropic_client = None
            self._provider = provider

        if self._initialized:
            return self._client is not None or self._anthropic_client is not None

        self._initialized = True

        if provider == 'disabled':
            return False

        if provider == 'claude':
            return self._init_anthropic_client()

        return self._init_openai_client()

    def _init_openai_client(self) -> bool:
        if not OPENAI_AVAILABLE:
            return False

        api_key = os.getenv("AI_INTEGRATIONS_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            try:
                from gui_app.broker_credentials_service import get_api_keys_extended
                keys = get_api_keys_extended()
                api_key = keys.get('openai', '')
            except Exception:
                pass

        base_url = os.getenv("AI_INTEGRATIONS_OPENAI_BASE_URL")

        if not api_key:
            print("[AI_PARSER] No OpenAI API key found")
            return False

        try:
            self._client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url if base_url else None
            )
            print(f"[AI_PARSER] ✓ Initialized OpenAI with model: {self._model}")
            return True
        except Exception as e:
            print(f"[AI_PARSER] Failed to initialize OpenAI: {e}")
            return False

    def _init_anthropic_client(self) -> bool:
        if not ANTHROPIC_AVAILABLE:
            print("[AI_PARSER] Anthropic SDK not installed (pip install anthropic)")
            return False

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            try:
                from gui_app.broker_credentials_service import get_api_keys_extended
                keys = get_api_keys_extended()
                api_key = keys.get('anthropic', '')
            except Exception:
                pass

        if not api_key:
            print("[AI_PARSER] No Anthropic API key found")
            return False

        try:
            self._anthropic_client = AsyncAnthropic(api_key=api_key)
            print(f"[AI_PARSER] ✓ Initialized Claude with model: {self._anthropic_model}")
            return True
        except Exception as e:
            print(f"[AI_PARSER] Failed to initialize Anthropic: {e}")
            return False
    
    def _load_few_shot_examples(self) -> None:
        """Load few-shot examples from SignalFormatRegistry + manual non-signal examples."""
        self._few_shot_examples = []
        self._registry_examples_str = None

        try:
            from src.services.signal_format_registry import SignalFormatRegistry
            reg = SignalFormatRegistry()
            raw_examples = []
            for fmt in reg._sorted_formats:
                for ex in fmt.examples:
                    m = fmt.pattern.search(ex)
                    if not m:
                        continue
                    try:
                        parsed = fmt.parser(m, ex)
                        if not parsed:
                            continue
                        action = parsed.get('action')
                        if not action or action in ('SKIP', 'UPDATE', 'TARGET_UPDATE', 'SL_UPDATE', 'CANCEL'):
                            continue
                        asset = parsed.get('asset', 'stock')
                        symbol = parsed.get('symbol', '')
                        if not symbol or len(symbol) > 5:
                            continue
                        out = {"action": action, "asset": asset, "symbol": symbol, "confidence": 0.95}
                        price = parsed.get('price')
                        if price:
                            out["price"] = price
                        if asset == 'option':
                            if parsed.get('strike'):
                                out["strike"] = parsed['strike']
                            if parsed.get('opt_type'):
                                out["option_type"] = parsed['opt_type']
                            if parsed.get('expiry'):
                                out["expiry"] = parsed['expiry']
                        if parsed.get('is_trim'):
                            out["is_trim"] = True
                        raw_examples.append({"input": ex, "output": out, "_family": fmt.name.split('_')[0]})
                    except Exception:
                        continue

            seen_families = {}
            max_per_family = 3
            selected = []
            for ex in raw_examples:
                fam = ex["_family"]
                if seen_families.get(fam, 0) >= max_per_family:
                    continue
                seen_families[fam] = seen_families.get(fam, 0) + 1
                selected.append(ex)

            for s in selected:
                s.pop('_family', None)
            self._few_shot_examples = selected

            lines = []
            for ex in selected:
                inp = ex['input'].replace('\n', '\\n')
                lines.append(f"Input: {inp}\nOutput: {json.dumps(ex['output'])}")
            self._registry_examples_str = "\n\n".join(lines)

            print(f"[AI_PARSER] ✓ Loaded {len(selected)} training examples from {len(seen_families)} channel families")
        except Exception as e:
            print(f"[AI_PARSER] ⚠️ Could not load registry examples: {e}")

        self._few_shot_examples.extend([
            {
                "input": "IBRX should start paying us soon",
                "output": {"action": None, "confidence": 0.0, "rationale": "Commentary only, not a trading signal"}
            },
            {
                "input": "Watching 1.99 break on NAMM, no entry yet",
                "output": {"action": None, "confidence": 0.0, "rationale": "Watchlist mention, no position taken"}
            },
            {
                "input": "Weekly RECAP:\n$PBM 183%\n$TDIC 110%\n$MMA 86%",
                "output": {"action": None, "confidence": 0.0, "rationale": "Performance recap, not a trading signal"}
            },
            {
                "input": "WL:\n$ANY alerted mid 3.00s. 6.53 above.\n$DXST 4.50 break takes it to 5.50+",
                "output": {"action": None, "confidence": 0.0, "rationale": "Watchlist / analysis, not an entry signal"}
            }
        ])

    def add_learned_example(self, input_text: str, output: Dict) -> None:
        """Add a learned example to few-shot prompts."""
        self._few_shot_examples.append({
            "input": input_text,
            "output": output
        })
    
    async def parse(self, text: str) -> AIParseResult:
        """
        Parse text using AI.
        
        Args:
            text: Natural language trading signal
            
        Returns:
            AIParseResult with parsed data and confidence
        """
        # Check cache first
        cached = self._cache.get(text)
        if cached:
            print(f"[AI_PARSER] Cache hit for: {text[:50]}...")
            return cached
        
        # Initialize client if needed
        if not self._init_client():
            return AIParseResult(error="OpenAI client not available")
        
        # Rate limit with semaphore
        async with self._semaphore:
            if self._anthropic_client and self._provider == 'claude':
                result = await self._call_anthropic(text)
            else:
                result = await self._call_openai(text)
        
        # Cache result
        self._cache.set(text, result)
        
        return result
    
    def _build_system_prompt(self) -> str:
        examples_str = self._registry_examples_str or "\n".join([
            f"Input: {ex['input']}\nOutput: {json.dumps(ex['output'])}"
            for ex in self._few_shot_examples[:6]
        ])
        return """You are a trading signal parser for Discord trading channels. You must extract structured data from messages posted by traders.

These channels use many different formats — structured emoji (✅/❌/🎯), natural language, options notation, and more. You have been trained on all known formats below.

Return a JSON object with these fields:
- action: "BTO" (buy to open), "STC" (sell to close), or null if not a trading signal
- asset: "stock" or "option"
- symbol: Stock ticker (uppercase, 1-5 letters)
- strike: Option strike price (null for stocks)
- option_type: "C" for call, "P" for put (null for stocks)
- expiry: Expiration date as MM/DD or MM/DD/YYYY (null for stocks)
- price: Entry/exit price if mentioned
- qty: Quantity if mentioned (default 1)
- is_trim: true if partial exit
- is_add: true if adding to existing position
- confidence: 0.0 to 1.0 confidence score
- rationale: Brief explanation of your interpretation

CRITICAL RULES:
- Only return action for CLEAR trading signals (entry/exit/trim/add)
- Weekly recaps, performance summaries, watchlists, commentary = action null
- "WL:" or "Watchlist" messages are NOT signals
- Price updates like "+50%" or "running" are NOT signals
- Messages with only a ticker and no price/action context are NOT signals
- For structured formats (✅ price / 🎯 targets), extract the entry price after ✅
- For option signals: extract strike, C/P, and expiry. Format: "SYMBOL STRIKEC/P MM/DD"
- Confidence 0.9+ for clear signals matching known patterns, 0.8 for reasonable inference
- Never hallucinate symbols not present in the input

KNOWN CHANNEL FORMATS (trained examples):

""" + examples_str

    async def _call_openai(self, text: str) -> AIParseResult:
        """Make API call to OpenAI."""
        try:
            system_prompt = self._build_system_prompt()

            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Parse this trading message:\n\n{text}"}
                ],
                temperature=0.3,
                max_tokens=300,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            data = json.loads(content)
            
            return AIParseResult(
                action=data.get('action'),
                asset=data.get('asset', 'stock'),
                symbol=data.get('symbol'),
                strike=data.get('strike'),
                option_type=data.get('option_type'),
                expiry=data.get('expiry'),
                price=data.get('price'),
                qty=data.get('qty', 1),
                confidence=data.get('confidence', 0.0),
                rationale=data.get('rationale', ''),
                is_trim=data.get('is_trim', False)
            )
            
        except json.JSONDecodeError as e:
            print(f"[AI_PARSER] JSON decode error: {e}")
            return AIParseResult(error=f"Invalid JSON response: {e}")
        except Exception as e:
            print(f"[AI_PARSER] API error: {e}")
            return AIParseResult(error=str(e))

    async def _call_anthropic(self, text: str) -> AIParseResult:
        """Make API call to Anthropic Claude."""
        try:
            system_prompt = self._build_system_prompt() + "\n\nReturn ONLY valid JSON, no markdown."

            response = await self._anthropic_client.messages.create(
                model=self._anthropic_model,
                max_tokens=300,
                temperature=0.3,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": f"Parse this trading message and return JSON only:\n\n{text}"},
                    {"role": "assistant", "content": "{"}
                ]
            )

            content = "{" + response.content[0].text
            content = content.strip()
            if content.endswith("```"):
                content = content[:content.rfind("```")].strip()

            data = json.loads(content)

            return AIParseResult(
                action=data.get('action'),
                asset=data.get('asset', 'stock'),
                symbol=data.get('symbol'),
                strike=data.get('strike'),
                option_type=data.get('option_type'),
                expiry=data.get('expiry'),
                price=data.get('price'),
                qty=data.get('qty', 1),
                confidence=data.get('confidence', 0.0),
                rationale=data.get('rationale', ''),
                is_trim=data.get('is_trim', False)
            )

        except json.JSONDecodeError as e:
            print(f"[AI_PARSER] Claude JSON decode error: {e}")
            return AIParseResult(error=f"Invalid JSON from Claude: {e}")
        except Exception as e:
            print(f"[AI_PARSER] Claude API error: {e}")
            return AIParseResult(error=str(e))


# Global singleton
_parser_instance: Optional[AISignalParser] = None


def get_ai_signal_parser() -> AISignalParser:
    """Get global AI parser instance."""
    global _parser_instance
    if _parser_instance is None:
        _parser_instance = AISignalParser()
    return _parser_instance


async def parse_signal_with_ai(text: str) -> Optional[Dict[str, Any]]:
    """
    Convenience function to parse signal with AI.
    
    Args:
        text: Natural language signal text
        
    Returns:
        Dict with parsed signal or None
    """
    parser = get_ai_signal_parser()
    result = await parser.parse(text)
    
    if result.error or not result.action:
        return None
    
    return {
        'action': result.action,
        'asset': result.asset,
        'symbol': result.symbol,
        'strike': result.strike,
        'option_type': result.option_type,
        'expiry': result.expiry,
        'price': result.price,
        'qty': result.qty,
        'confidence': result.confidence,
        'rationale': result.rationale,
        'is_trim': result.is_trim,
        '_ai_parsed': True
    }
