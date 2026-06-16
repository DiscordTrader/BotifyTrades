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
    from gui_app.config_service import (
        AI_PROVIDER_DEFAULT_MODELS as _PROVIDER_DEFAULTS_SHARED,
        AI_PROVIDER_MODEL_PREFIXES as _PROVIDER_PREFIXES_SHARED,
    )
except ImportError:
    _PROVIDER_DEFAULTS_SHARED = None
    _PROVIDER_PREFIXES_SHARED = None

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
    is_conditional: bool = False
    trigger_price: Optional[float] = None
    trigger_type: str = "over"
    profit_targets: Optional[List[float]] = None
    stop_loss: Optional[float] = None
    stop_loss_pct: Optional[float] = None


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
    
    _PROVIDER_DEFAULTS = _PROVIDER_DEFAULTS_SHARED or {
        'openai': 'gpt-4o-mini',
        'claude': 'claude-haiku-4-5-20251001',
        'gemini': 'gemini-2.0-flash',
    }
    _PROVIDER_PREFIXES = _PROVIDER_PREFIXES_SHARED or {
        'openai': ('gpt-', 'o1', 'o3', 'o4'),
        'claude': ('claude-',),
        'gemini': ('gemini-',),
    }

    def __init__(self, max_concurrent: int = 3):
        self._client: Optional[AsyncOpenAI] = None
        self._anthropic_client = None
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._cache = AISignalParserCache()
        self._model = "gpt-4o-mini"
        self._anthropic_model = "claude-haiku-4-5-20251001"
        self._gemini_model = "gemini-2.0-flash"
        self._provider = None
        self._initialized = False
        self._few_shot_examples: List[Dict] = []
        self._load_few_shot_examples()

    def _resolve_model(self, provider: str) -> str:
        """Read model from ai_settings, validate it belongs to this provider."""
        try:
            from gui_app.database import get_ai_settings
            settings = get_ai_settings()
            model = settings.get('model', '')
            if model:
                prefixes = self._PROVIDER_PREFIXES.get(provider, ())
                if any(model.startswith(p) for p in prefixes):
                    return model
        except Exception:
            pass
        return self._PROVIDER_DEFAULTS.get(provider, 'gpt-4o-mini')

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
            self._gemini_client = None
            self._provider = provider

        if self._initialized:
            return (self._client is not None
                    or self._anthropic_client is not None
                    or (hasattr(self, '_gemini_client') and self._gemini_client is not None))

        self._initialized = True

        if provider == 'disabled':
            return False

        if provider == 'claude':
            return self._init_anthropic_client()

        if provider == 'gemini':
            return self._init_gemini_client()

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
            self._model = self._resolve_model('openai')
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
            self._anthropic_model = self._resolve_model('claude')
            print(f"[AI_PARSER] ✓ Initialized Claude with model: {self._anthropic_model}")
            return True
        except Exception as e:
            print(f"[AI_PARSER] Failed to initialize Anthropic: {e}")
            return False

    def _init_gemini_client(self) -> bool:
        try:
            from google import genai as _genai
        except ImportError:
            print("[AI_PARSER] Google GenAI SDK not installed (pip install google-genai)")
            return False

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            try:
                from gui_app.broker_credentials_service import get_api_keys_extended
                keys = get_api_keys_extended()
                api_key = keys.get('gemini', '')
            except Exception:
                pass

        if not api_key:
            print("[AI_PARSER] No Gemini API key found")
            return False

        try:
            self._gemini_client = _genai.Client(api_key=api_key)
            self._gemini_model = self._resolve_model('gemini')
            print(f"[AI_PARSER] ✓ Initialized Gemini with model: {self._gemini_model}")
            return True
        except Exception as e:
            print(f"[AI_PARSER] Failed to initialize Gemini: {e}")
            return False

    def _load_few_shot_examples(self) -> None:
        """Load few-shot examples from SignalFormatRegistry + manual non-signal examples."""
        self._few_shot_examples = []
        self._registry_examples_str = None

        try:
            from src.services.signal_format_registry import get_signal_format_registry
            reg = get_signal_format_registry()
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
            if self._provider == 'gemini' and hasattr(self, '_gemini_client') and self._gemini_client:
                result = await self._call_gemini(text)
            elif self._anthropic_client and self._provider == 'claude':
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
- price: Entry/exit price if mentioned (the trigger/break price for conditional entries)
- qty: Quantity if mentioned (default 1)
- is_trim: true if partial exit
- is_add: true if adding to existing position
- is_conditional: true if the entry depends on a price breakout/trigger (NOT immediate market buy)
- trigger_price: The price that must be broken/reached before entering (same as price for conditional)
- trigger_type: "over" (break above) or "under" (break below), default "over"
- profit_targets: Array of target prices [2.35, 2.50, 3.00] extracted from "for X...Y...Z" or 🎯
- stop_loss: Fixed stop loss price if mentioned (from ❌ or "SL" text)
- stop_loss_pct: Percentage stop loss if mentioned (e.g. -10% -> 10)
- confidence: 0.0 to 1.0 confidence score
- rationale: Brief explanation of your interpretation

CONDITIONAL ORDER DETECTION — these are NOT immediate buys, they are conditional triggers:
- "will enter [if/only if] [it] breaks [and holds] PRICE" -> is_conditional=true, trigger_price=PRICE
- "will enter at PRICE break" -> is_conditional=true
- "clear break of PRICE for TARGETS" -> is_conditional=true
- "SYMBOL over VWAP/PRICE" -> is_conditional=true
- "will re-enter if it breaks PRICE" -> is_conditional=true
- "break of PRICE only for TARGETS" -> is_conditional=true
- "lotto [at] PRICE" -> is_conditional=false (immediate small entry)
- "Scalping SYMBOL [at/here] PRICE" -> is_conditional=false (immediate entry)
- "Small SYMBOL [at] PRICE" -> is_conditional=false (immediate small entry)
- "in again at PRICE" -> is_conditional=false (immediate re-entry)
- Structured ✅ PRICE 🎯 TARGETS -> is_conditional=true (standard conditional)

TARGET EXTRACTION from "for" text:
- "for 3.51-4.00-4.30" -> profit_targets: [3.51, 4.00, 4.30]
- "for 2.34...2.50...2.69...3.00" -> profit_targets: [2.34, 2.50, 2.69, 3.00]
- "🎯 5% 10% 15%" -> profit_targets as percentages (leave as [5, 10, 15] with is_pct flag)
- "for PRICE retest" -> profit_targets: [PRICE]

CRITICAL RULES:
- Only return action for CLEAR trading signals (entry/exit/trim/add)
- Weekly recaps, performance summaries, watchlists, commentary = action null
- "WL:" or "Watchlist" messages are NOT entry signals — they are analysis
- Price updates like "+50%" or "running" or "halted" are NOT signals
- "PT hit", "all PTs hit", "paid us" are NOT signals (past tense updates)
- Messages with only a ticker and no price/action context are NOT signals
- "alert valid again" is NOT a signal (no price)
- For structured formats (✅ price / 🎯 targets), extract the entry price after ✅
- For option signals: extract strike, C/P, and expiry
- Confidence 0.9+ for clear signals matching known patterns, 0.8 for reasonable inference
- Never hallucinate symbols not present in the input

TRADE UPDATE DETECTION (NEVER treat these as signals — return action null):
- "SYMBOL LOW-HIGH" with pink_flame emoji (e.g. "STI 31-47.69 <pink_flame>") = profit update showing entry-to-high range
- "SYMBOL LOW-HIGH so far" = progress update on existing trade
- "SYMBOL LOW-HIGH" as a reply to a previous message = trade performance update
- Any message with pink_flame/fire emoji after a price range = celebrating profit, NOT a new entry
- "SYMBOL +N%" = percentage gain update, NOT a signal
- "SYMBOL paid us", "top nailed", "all fibs hit" = past tense celebration
- "stopped out" = already stopped, NOT a new exit signal
- The format "SYMBOL ENTRY_PRICE-CURRENT_PRICE" is ALWAYS a trade update showing how a trade performed, NEVER a new entry

KNOWN CHANNEL FORMATS (trained examples):

""" + examples_str

    def _build_result(self, data: Dict) -> AIParseResult:
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
            is_trim=data.get('is_trim', False),
            is_conditional=data.get('is_conditional', False),
            trigger_price=data.get('trigger_price') or data.get('price'),
            trigger_type=data.get('trigger_type', 'over'),
            profit_targets=data.get('profit_targets'),
            stop_loss=data.get('stop_loss'),
            stop_loss_pct=data.get('stop_loss_pct'),
        )

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
            return self._build_result(data)

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
            return self._build_result(data)

        except json.JSONDecodeError as e:
            print(f"[AI_PARSER] Claude JSON decode error: {e}")
            return AIParseResult(error=f"Invalid JSON from Claude: {e}")
        except Exception as e:
            print(f"[AI_PARSER] Claude API error: {e}")
            return AIParseResult(error=str(e))

    async def _call_gemini(self, text: str) -> AIParseResult:
        """Make API call to Google Gemini."""
        try:
            import asyncio
            system_prompt = self._build_system_prompt() + "\n\nReturn ONLY valid JSON, no markdown code blocks."
            user_msg = f"Parse this trading message and return JSON only:\n\n{text}"
            full_prompt = f"{system_prompt}\n\n{user_msg}"

            response = await asyncio.to_thread(
                self._gemini_client.models.generate_content,
                model=self._gemini_model,
                contents=full_prompt
            )

            content = response.text.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:content.rfind("```")].strip()
            if not content.startswith("{"):
                start = content.find("{")
                if start >= 0:
                    content = content[start:]

            data = json.loads(content)
            return self._build_result(data)

        except json.JSONDecodeError as e:
            print(f"[AI_PARSER] Gemini JSON decode error: {e}")
            return AIParseResult(error=f"Invalid JSON from Gemini: {e}")
        except Exception as e:
            print(f"[AI_PARSER] Gemini API error: {e}")
            return AIParseResult(error=str(e))


    async def parse_exit_intent(
        self,
        message_text: str,
        open_positions: List[Dict[str, Any]],
    ) -> 'CorrectionResult':
        """
        Focused exit-intent prompt with open position context.
        Used by SignalCorrectionService Layer 2 — not the general signal parser.

        Gate 3: AI output symbol is hard-validated against open_positions.
        Returns CorrectionResult — caller checks .corrected_symbol and .rejected.
        """
        from src.services.signal_correction import CorrectionResult

        if not self._init_client():
            return CorrectionResult(reason='AI provider not configured')

        pos_lines = '\n'.join(
            f"  - {p['symbol']} ({p.get('asset_type', 'option')}, opened {p.get('entry_time', 'unknown')})"
            for p in open_positions
        )
        open_syms = {p['symbol'].upper() for p in open_positions}

        system_prompt = (
            "You are analyzing a trader's Discord message to determine if it is an exit signal "
            "for one of their open positions listed below.\n\n"
            f"Open positions in this channel:\n{pos_lines}\n\n"
            "Return ONLY valid JSON:\n"
            '{"is_exit": true/false, "symbol": "<exact symbol from list or null>", '
            '"corrected_from": "<ticker in message or null>", '
            '"confidence": 0.0-1.0, "reason": "<brief explanation>"}\n\n'
            "RULES:\n"
            "- symbol MUST be one of the listed positions — never invent others\n"
            "- 'hit my SL', 'took the loss', 'out here', 'stopped out', 'closed', 'sold' are exits\n"
            "- Comments, questions, analysis are NOT exits — return is_exit=false\n"
            "- Only return is_exit=true if highly confident this is an actionable exit"
        )
        user_content = f'Message: "{message_text}"'

        try:
            raw_text = None
            async with self._semaphore:
                if self._provider == 'gemini' and hasattr(self, '_gemini_client') and self._gemini_client:
                    resp = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: self._gemini_client.models.generate_content(
                                model=self._gemini_model if hasattr(self, '_gemini_model') else 'gemini-2.0-flash',
                                contents=f'{system_prompt}\n\n{user_content}\n\nReturn ONLY valid JSON.'
                            )
                        ),
                        timeout=8.0,
                    )
                    raw_text = resp.text.strip()
                elif self._anthropic_client and self._provider == 'claude':
                    resp = await asyncio.wait_for(
                        self._anthropic_client.messages.create(
                            model=self._anthropic_model,
                            max_tokens=256,
                            system=system_prompt,
                            messages=[
                                {'role': 'user', 'content': user_content},
                                {'role': 'assistant', 'content': '{'},
                            ],
                        ),
                        timeout=8.0,
                    )
                    raw_text = '{' + (resp.content[0].text or '}')
                elif self._client:
                    resp = await asyncio.wait_for(
                        self._client.chat.completions.create(
                            model=self._model,
                            messages=[
                                {'role': 'system', 'content': system_prompt},
                                {'role': 'user', 'content': user_content},
                            ],
                            max_tokens=256,
                            temperature=0.1,
                            response_format={'type': 'json_object'},
                        ),
                        timeout=8.0,
                    )
                    raw_text = resp.choices[0].message.content or '{}'
                else:
                    return CorrectionResult(reason='no AI client available')

            # Strip markdown fences if present
            if raw_text and raw_text.startswith('```'):
                raw_text = raw_text.split('\n', 1)[1] if '\n' in raw_text else raw_text[3:]
            if raw_text and raw_text.endswith('```'):
                raw_text = raw_text[:raw_text.rfind('```')].strip()

            import json as _json
            data = _json.loads(raw_text)

            if not data.get('is_exit'):
                return CorrectionResult(reason=f"AI: not an exit — {data.get('reason', '')}")

            conf = float(data.get('confidence', 0))
            if conf < 0.75:
                print(f'[CORRECTION] ⚠️ AI exit-intent below threshold (conf={conf:.2f}): {message_text[:60]}')
                return CorrectionResult(reason=f'AI confidence {conf:.2f} < 0.75 threshold')

            sym = (data.get('symbol') or '').upper().strip()

            # Gate 3: symbol must be in open positions
            if sym not in open_syms:
                print(f'[CORRECTION] ⚠️ AI returned symbol {sym!r} not in open positions {open_syms} — rejected')
                return CorrectionResult(
                    rejected=True,
                    reason=f'AI symbol {sym!r} not in open positions (hallucination guard)',
                )

            corrected_from = data.get('corrected_from') or None
            print(f'[CORRECTION] ✅ Layer2 AI: {corrected_from!r} → {sym!r} (conf={conf:.2f}): {data.get("reason", "")}')
            return CorrectionResult(
                corrected_symbol=sym,
                original_symbol=corrected_from or sym,
                correction_method='ai',
                confidence=conf,
                reason=data.get('reason', ''),
            )

        except Exception as e:
            print(f'[CORRECTION] ⚠️ parse_exit_intent error: {e}')
            return CorrectionResult(reason=f'AI parse error: {e}')


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
    
    d = {
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
        'is_conditional': result.is_conditional,
        'trigger_price': result.trigger_price,
        'trigger_type': result.trigger_type,
        'profit_targets': result.profit_targets or [],
        'stop_loss': result.stop_loss,
        'stop_loss_pct': result.stop_loss_pct,
        '_ai_parsed': True
    }
    return d
