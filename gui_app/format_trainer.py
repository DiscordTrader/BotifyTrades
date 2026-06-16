"""
AI-Powered Signal Format Trainer
Learns new signal formats from examples and creates parsing templates.
Uses "teach once, use forever" approach to minimize AI costs.
"""
import re
import json
import hashlib
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from .config_service import AI_PROVIDER_DEFAULT_MODELS, AI_PROVIDER_MODEL_PREFIXES


class FormatTrainer:
    """Service for learning and applying signal formats using AI."""
    
    def __init__(self):
        self._openai_client = None
        self._anthropic_client = None
        self._openai_available = None
    
    def _get_openai_client(self):
        """Get AI client based on user's provider preference from GUI.
        Routes to Claude, Gemini, or OpenAI based on Settings > AI & Market Data APIs.
        """
        try:
            from .config_service import get_ai_provider, load_config
            
            provider = get_ai_provider()
            
            # Check if provider changed - reset cache
            cached_provider = getattr(self, '_cached_provider', None)
            if cached_provider != provider:
                self._openai_client = None
                self._anthropic_client = None
                self._cached_provider = provider
            
            # Return cached client if available
            if self._openai_client is not None:
                return self._openai_client
            
            # Check if AI is disabled
            if provider == 'disabled':
                self._openai_available = False
                print("[FORMAT_TRAINER] AI is disabled in settings")
                return None
            
            from openai import OpenAI
            
            # Use user's OpenAI API key
            if provider == 'openai':
                user_api_key = os.environ.get('OPENAI_API_KEY')

                if not user_api_key:
                    api_keys = load_config('api_keys')
                    if api_keys and api_keys.get('openai'):
                        user_api_key = api_keys['openai']

                if user_api_key:
                    self._openai_client = OpenAI(api_key=user_api_key)
                    self._openai_available = True
                    print("[FORMAT_TRAINER] Using user's OpenAI API key")
                    return self._openai_client
                else:
                    print("[FORMAT_TRAINER] OpenAI API key not configured")
                    self._openai_available = False
                    return None

            if provider == 'claude':
                return self._init_claude_trainer()

            if provider == 'gemini':
                return self._init_gemini_trainer()

            self._openai_available = False
            return None
                
        except Exception as e:
            print(f"[FORMAT_TRAINER] OpenAI initialization failed: {e}")
            self._openai_available = False
            return None
    
    def _init_claude_trainer(self):
        if self._anthropic_client is not None:
            self._openai_available = True
            return self._anthropic_client
        try:
            from anthropic import Anthropic
            from .broker_credentials_service import get_api_keys_extended
            keys = get_api_keys_extended()
            api_key = os.environ.get('ANTHROPIC_API_KEY') or keys.get('anthropic', '')
            if not api_key:
                print("[FORMAT_TRAINER] Anthropic API key not configured")
                self._openai_available = False
                return None
            self._anthropic_client = Anthropic(api_key=api_key)
            self._openai_available = True
            print("[FORMAT_TRAINER] Using Claude (Anthropic) API")
            return self._anthropic_client
        except ImportError:
            print("[FORMAT_TRAINER] Anthropic SDK not installed (pip install anthropic)")
            self._openai_available = False
            return None
        except Exception as e:
            print(f"[FORMAT_TRAINER] Anthropic initialization failed: {e}")
            self._openai_available = False
            return None

    def _init_gemini_trainer(self):
        if getattr(self, '_gemini_client', None) is not None:
            self._openai_available = True
            return self._gemini_client
        try:
            from google import genai as _genai
            from .broker_credentials_service import get_api_keys_extended
            keys = get_api_keys_extended()
            api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY') or keys.get('gemini', '')
            if not api_key:
                print("[FORMAT_TRAINER] Gemini API key not configured")
                self._openai_available = False
                return None
            self._gemini_client = _genai.Client(api_key=api_key)
            self._openai_available = True
            print("[FORMAT_TRAINER] Using Gemini (Google) API")
            return self._gemini_client
        except ImportError:
            print("[FORMAT_TRAINER] Google GenAI SDK not installed (pip install google-genai)")
            self._openai_available = False
            return None
        except Exception as e:
            print(f"[FORMAT_TRAINER] Gemini initialization failed: {e}")
            self._openai_available = False
            return None

    def _is_claude_provider(self) -> bool:
        return getattr(self, '_cached_provider', None) == 'claude'

    def _is_gemini_provider(self) -> bool:
        return getattr(self, '_cached_provider', None) == 'gemini'

    _DEFAULT_MODELS = AI_PROVIDER_DEFAULT_MODELS
    _MODEL_PREFIXES = AI_PROVIDER_MODEL_PREFIXES

    def _get_model(self) -> str:
        """Read model from ai_settings DB; validate it belongs to provider, else fall back to default."""
        provider = getattr(self, '_cached_provider', 'openai') or 'openai'
        try:
            from . import database as _db
            settings = _db.get_ai_settings()
            model = settings.get('model', '')
            if model:
                prefixes = self._MODEL_PREFIXES.get(provider, ())
                if any(model.startswith(p) for p in prefixes):
                    return model
        except Exception:
            pass
        return self._DEFAULT_MODELS.get(provider, 'gpt-4o-mini')

    def is_ai_available(self) -> bool:
        """Check if AI is available."""
        return self._get_openai_client() is not None
    
    def get_message_hash(self, message: str) -> str:
        """Generate a hash for a message (for caching)."""
        normalized = re.sub(r'\s+', ' ', message.strip().lower())
        return hashlib.md5(normalized.encode()).hexdigest()
    
    def learn_format_from_example(self, example_signal: str, 
                                   user_guidance: Optional[str] = None) -> Dict:
        """
        Use AI to learn a new signal format from an example.
        Returns parsed fields, suggested regex, and field mappings.
        """
        client = self._get_openai_client()
        
        if not client:
            from .config_service import get_ai_provider
            provider = get_ai_provider()
            if provider == 'disabled':
                error_msg = 'AI is disabled. Enable it in Settings > AI & Market Data APIs.'
            elif provider == 'claude':
                error_msg = 'Anthropic API key not configured. Add it in Settings > AI & Market Data APIs.'
            elif provider == 'gemini':
                error_msg = 'Gemini API key not configured. Add it in Settings > AI & Market Data APIs.'
            else:
                error_msg = 'OpenAI API key not configured. Add it in Settings > AI & Market Data APIs.'
            return {
                'success': False,
                'error': error_msg,
                'ai_powered': False
            }
        
        try:
            system_prompt = """You are a trading signal format analyzer. Analyze the given signal example and extract:
1. The signal type (BTO/STC for options, BUY/SELL for stocks)
2. Symbol/Ticker
3. Entry price
4. Profit targets (if any)
5. Stop loss (if any)
6. Quantity (if specified)
7. For options: strike price, expiration date, call/put type

Respond with a JSON object containing:
{
    "format_name": "Short descriptive name",
    "description": "Brief description of this format",
    "parsed_fields": {
        "action": "BTO/STC/BUY/SELL",
        "symbol": "TICKER",
        "entry_price": 0.00,
        "quantity": null or number,
        "profit_targets": [array of prices] or null,
        "stop_loss": number or null,
        "is_option": true/false,
        "strike": number or null,
        "expiration": "YYYY-MM-DD" or null,
        "option_type": "C" or "P" or null
    },
    "field_mappings": {
        "action_keywords": ["BTO", "Buy to Open", etc],
        "symbol_pattern": "description of where symbol appears",
        "price_pattern": "description of price format",
        "targets_pattern": "description of targets format if any"
    },
    "suggested_regex": "A regex pattern to match this format (or null if too complex)",
    "confidence": 0.0-1.0
}

Only include fields that are actually present in the signal. Be precise with the extraction."""

            user_content = f"Analyze this trading signal:\n```\n{example_signal}\n```"
            if user_guidance:
                user_content += f"\n\nUser guidance: {user_guidance}"

            if self._is_gemini_provider():
                response = client.models.generate_content(
                    model=self._get_model(),
                    contents=f"{system_prompt}\n\n{user_content}\n\nReturn ONLY valid JSON, no markdown."
                )
                result_text = response.text.strip()
                if result_text.startswith("```"):
                    result_text = result_text.split("\n", 1)[1] if "\n" in result_text else result_text[3:]
                if result_text.endswith("```"):
                    result_text = result_text[:result_text.rfind("```")].strip()
                if not result_text.startswith("{"):
                    start = result_text.find("{")
                    if start >= 0:
                        result_text = result_text[start:]
            elif self._is_claude_provider():
                response = client.messages.create(
                    model=self._get_model(),
                    max_tokens=800,
                    temperature=0.3,
                    system=system_prompt,
                    messages=[
                        {"role": "user", "content": user_content},
                        {"role": "assistant", "content": "{"}
                    ]
                )
                result_text = "{" + (response.content[0].text or "}")
                if result_text.endswith("```"):
                    result_text = result_text[:result_text.rfind("```")].strip()
            else:
                response = client.chat.completions.create(
                    model=self._get_model(),
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                    max_tokens=800,
                    temperature=0.3,
                    response_format={"type": "json_object"}
                )
                result_text = response.choices[0].message.content or "{}"
            result = json.loads(result_text)
            
            return {
                'success': True,
                'ai_powered': True,
                'format_name': result.get('format_name', 'Custom Format'),
                'description': result.get('description', ''),
                'parsed_fields': result.get('parsed_fields', {}),
                'field_mappings': result.get('field_mappings', {}),
                'suggested_regex': result.get('suggested_regex'),
                'confidence': result.get('confidence', 0.8)
            }
            
        except json.JSONDecodeError as e:
            print(f"[FORMAT_TRAINER] JSON parse error: {e}")
            return {
                'success': False,
                'error': 'Failed to parse AI response',
                'ai_powered': True
            }
        except Exception as e:
            print(f"[FORMAT_TRAINER] Error learning format: {e}")
            return {
                'success': False,
                'error': str(e),
                'ai_powered': True
            }
    
    def parse_signal_with_ai(self, signal_text: str) -> Dict:
        """
        Parse a signal using AI when no stored format matches.
        This is the fallback for unrecognized formats.
        """
        client = self._get_openai_client()
        
        if not client:
            return {
                'success': False,
                'error': 'AI not available',
                'ai_powered': False
            }

        try:
            system_prompt = """You are a trading signal parser. Extract trading information from the given signal.

Return a JSON object:
{
    "is_trading_signal": true/false,
    "action": "BTO" or "STC" or "BUY" or "SELL" or null,
    "symbol": "TICKER" or null,
    "entry_price": number or null,
    "quantity": number or null,
    "profit_targets": [array] or null,
    "stop_loss": number or null,
    "is_option": true/false,
    "strike": number or null,
    "expiration": "MM/DD" or "YYYY-MM-DD" or null,
    "option_type": "C" or "P" or null,
    "confidence": 0.0-1.0
}

If it's not a trading signal, set is_trading_signal to false and action to null."""

            if self._is_gemini_provider():
                response = client.models.generate_content(
                    model=self._get_model(),
                    contents=f"{system_prompt}\n\nParse this message:\n{signal_text}\n\nReturn ONLY valid JSON."
                )
                raw = response.text.strip()
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:raw.rfind("```")].strip()
                if not raw.startswith("{"):
                    start = raw.find("{")
                    if start >= 0:
                        raw = raw[start:]
                result = json.loads(raw)
            elif self._is_claude_provider():
                response = client.messages.create(
                    model=self._get_model(),
                    max_tokens=400,
                    temperature=0.2,
                    system=system_prompt,
                    messages=[
                        {"role": "user", "content": f"Parse this message:\n{signal_text}"},
                        {"role": "assistant", "content": "{"}
                    ]
                )
                raw = "{" + (response.content[0].text or "}")
                if raw.endswith("```"):
                    raw = raw[:raw.rfind("```")].strip()
                result = json.loads(raw)
            else:
                response = client.chat.completions.create(
                    model=self._get_model(),
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Parse this message:\n{signal_text}"}
                    ],
                    max_tokens=400,
                    temperature=0.2,
                    response_format={"type": "json_object"}
                )
                result = json.loads(response.choices[0].message.content or "{}")
            
            return {
                'success': True,
                'ai_powered': True,
                'is_trading_signal': result.get('is_trading_signal', False),
                'parsed': result
            }
            
        except Exception as e:
            print(f"[FORMAT_TRAINER] Error parsing signal: {e}")
            return {
                'success': False,
                'error': str(e),
                'ai_powered': True
            }
    
    def try_parse_with_learned_formats(self, signal_text: str) -> Optional[Dict]:
        """
        Try to parse a signal using learned formats from database.
        Returns parsed result if a format matches, None otherwise.
        """
        try:
            from . import database as db
            
            message_hash = self.get_message_hash(signal_text)
            cached = db.get_cached_signal_parse(message_hash)
            if cached:
                if cached.get('format_id'):
                    db.increment_format_usage(cached['format_id'], success=True)
                return cached['parsed_result']
            
            formats = db.get_learned_signal_formats(enabled_only=True)
            
            for fmt in formats:
                regex_pattern = fmt.get('regex_pattern')
                if regex_pattern:
                    try:
                        match = re.search(regex_pattern, signal_text, re.IGNORECASE | re.MULTILINE)
                        if match:
                            field_mappings = json.loads(fmt.get('field_mappings', '{}'))
                            parsed_fields = json.loads(fmt.get('parsed_fields', '{}'))
                            
                            result = self._apply_regex_match(match, field_mappings, parsed_fields)
                            if result:
                                db.cache_signal_parse(message_hash, fmt['id'], result)
                                db.increment_format_usage(fmt['id'], success=True)
                                return result
                    except re.error as e:
                        print(f"[FORMAT_TRAINER] Invalid regex in format {fmt['id']}: {e}")
                        continue
            
            return None
            
        except Exception as e:
            print(f"[FORMAT_TRAINER] Error trying learned formats: {e}")
            return None
    
    def _apply_regex_match(self, match: re.Match, field_mappings: Dict, 
                           template_fields: Dict) -> Optional[Dict]:
        """Apply regex match groups to create parsed result."""
        try:
            result = dict(template_fields)
            
            groups = match.groupdict() if match.groupdict() else {}
            if not groups:
                groups = {f'group_{i}': g for i, g in enumerate(match.groups())}
            
            for field_name, mapping_info in field_mappings.items():
                if isinstance(mapping_info, dict) and 'group' in mapping_info:
                    group_name = mapping_info['group']
                    if group_name in groups and groups[group_name]:
                        value = groups[group_name]
                        if mapping_info.get('type') == 'float':
                            try:
                                value = float(value.replace('$', '').replace(',', ''))
                            except:
                                pass
                        elif mapping_info.get('type') == 'int':
                            try:
                                value = int(value)
                            except:
                                pass
                        result[field_name] = value
            
            return result
            
        except Exception as e:
            print(f"[FORMAT_TRAINER] Error applying regex match: {e}")
            return None
    
    def validate_and_save_format(self, name: str, description: str, 
                                  example_signal: str, parsed_fields: Dict,
                                  regex_pattern: Optional[str], 
                                  field_mappings: Dict) -> Dict:
        """Validate and save a learned format to database."""
        try:
            from . import database as db
            
            if regex_pattern:
                try:
                    re.compile(regex_pattern)
                except re.error as e:
                    return {
                        'success': False,
                        'error': f'Invalid regex pattern: {e}'
                    }
            
            format_id = db.save_learned_signal_format(
                name=name,
                description=description,
                example_signal=example_signal,
                parsed_fields=parsed_fields,
                regex_pattern=regex_pattern or '',
                field_mappings=field_mappings
            )
            
            if format_id:
                return {
                    'success': True,
                    'format_id': format_id,
                    'message': f'Format "{name}" saved successfully!'
                }
            else:
                return {
                    'success': False,
                    'error': 'Failed to save format to database'
                }
                
        except Exception as e:
            print(f"[FORMAT_TRAINER] Error saving format: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_all_formats(self, include_disabled: bool = False) -> List[Dict]:
        """Get all learned formats."""
        try:
            from . import database as db
            return db.get_learned_signal_formats(enabled_only=not include_disabled)
        except Exception as e:
            print(f"[FORMAT_TRAINER] Error getting formats: {e}")
            return []
    
    def toggle_format(self, format_id: int, enabled: bool) -> bool:
        """Enable or disable a format."""
        try:
            from . import database as db
            return db.update_signal_format(format_id, is_enabled=1 if enabled else 0)
        except Exception as e:
            print(f"[FORMAT_TRAINER] Error toggling format: {e}")
            return False
    
    def delete_format(self, format_id: int) -> bool:
        """Delete a format."""
        try:
            from . import database as db
            return db.delete_signal_format(format_id)
        except Exception as e:
            print(f"[FORMAT_TRAINER] Error deleting format: {e}")
            return False


    def discover_formats_from_messages(self, messages: List[str], 
                                         channel_name: str = "Unknown Channel") -> Dict:
        """
        Analyze multiple messages to discover and learn signal formats automatically.
        Uses AI to identify trading signals and group them by format type.
        
        Args:
            messages: List of message texts from a channel
            channel_name: Name of the channel for labeling
            
        Returns:
            Dictionary with discovered formats and statistics
        """
        client = self._get_openai_client()
        
        if not client:
            from .config_service import get_ai_provider
            provider = get_ai_provider()
            if provider == 'disabled':
                error_msg = 'AI is disabled. Enable it in Settings > AI & Market Data APIs.'
            elif provider == 'claude':
                error_msg = 'Anthropic API key not configured. Add it in Settings > AI & Market Data APIs.'
            elif provider == 'gemini':
                error_msg = 'Gemini API key not configured. Add it in Settings > AI & Market Data APIs.'
            else:
                error_msg = 'OpenAI API key not configured. Add it in Settings > AI & Market Data APIs.'
            return {
                'success': False,
                'error': error_msg,
                'formats_discovered': 0
            }
        
        if not messages:
            return {
                'success': False,
                'error': 'No messages provided to analyze',
                'formats_discovered': 0
            }
        
        messages = [m.strip() for m in messages if m.strip()]
        messages = messages[:50]
        
        try:
            system_prompt = """You are a trading signal format analyzer. Analyze these messages from a Discord trading channel and identify UNIQUE signal formats.

For each distinct format pattern you find:
1. Identify if it's a trading signal (BTO/STC for options, BUY/SELL for stocks)
2. Extract the format structure (what fields are present and in what order)
3. Group similar messages that use the same format

Return a JSON object:
{
    "formats": [
        {
            "format_name": "Short descriptive name",
            "format_type": "option" or "stock",
            "description": "Brief description of this format pattern",
            "example_message": "One representative example from the messages",
            "pattern_structure": "Description like: ACTION QTY SYMBOL STRIKE TYPE EXPIRY @ PRICE",
            "parsed_example": {
                "action": "BTO/STC/BUY/SELL",
                "symbol": "TICKER",
                "entry_price": 0.00,
                "quantity": null or number,
                "is_option": true/false,
                "strike": number or null,
                "expiration": "MM/DD" or null,
                "option_type": "C" or "P" or null
            },
            "suggested_regex": "Regex pattern or null if too complex",
            "message_count": "How many of the provided messages match this format",
            "confidence": 0.0-1.0
        }
    ],
    "non_signals": ["List of messages that are NOT trading signals"],
    "total_signals_found": number,
    "summary": "Brief summary of what was found"
}

Only include UNIQUE formats - do not duplicate similar patterns. Focus on formats that appear multiple times."""

            messages_text = "\n---\n".join(messages)
            user_content = f"Analyze these {len(messages)} messages from '{channel_name}' channel:\n\n{messages_text}"

            if self._is_gemini_provider():
                response = client.models.generate_content(
                    model=self._get_model(),
                    contents=f"{system_prompt}\n\n{user_content}\n\nReturn ONLY valid JSON."
                )
                raw = response.text.strip()
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:raw.rfind("```")].strip()
                if not raw.startswith("{"):
                    start = raw.find("{")
                    if start >= 0:
                        raw = raw[start:]
                result = json.loads(raw)
            elif self._is_claude_provider():
                response = client.messages.create(
                    model=self._get_model(),
                    max_tokens=2000,
                    temperature=0.3,
                    system=system_prompt,
                    messages=[
                        {"role": "user", "content": user_content},
                        {"role": "assistant", "content": "{"}
                    ]
                )
                raw = "{" + (response.content[0].text or "}")
                if raw.endswith("```"):
                    raw = raw[:raw.rfind("```")].strip()
                result = json.loads(raw)
            else:
                response = client.chat.completions.create(
                    model=self._get_model(),
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                    max_tokens=2000,
                    temperature=0.3,
                    response_format={"type": "json_object"}
                )
                result = json.loads(response.choices[0].message.content or "{}")
            
            formats_discovered = result.get('formats', [])
            formats_saved = []
            formats_skipped = []
            
            from . import database as db
            existing_formats = db.get_learned_signal_formats(enabled_only=False)
            existing_names = {f.get('name', '').lower() for f in existing_formats}
            
            for fmt in formats_discovered:
                format_name = fmt.get('format_name', 'Unknown Format')
                
                if format_name.lower() in existing_names:
                    formats_skipped.append({
                        'name': format_name,
                        'reason': 'Format with similar name already exists'
                    })
                    continue
                
                if fmt.get('confidence', 0) < 0.6:
                    formats_skipped.append({
                        'name': format_name,
                        'reason': f"Low confidence ({fmt.get('confidence', 0)*100:.0f}%)"
                    })
                    continue
                
                try:
                    format_id = db.save_signal_format(
                        name=f"{format_name} ({channel_name})",
                        description=fmt.get('description', ''),
                        example_signal=fmt.get('example_message', ''),
                        parsed_fields=fmt.get('parsed_example', {}),
                        field_mappings={
                            'pattern_structure': fmt.get('pattern_structure', ''),
                            'format_type': fmt.get('format_type', 'option')
                        },
                        regex_pattern=fmt.get('suggested_regex')
                    )
                    
                    if format_id:
                        formats_saved.append({
                            'id': format_id,
                            'name': f"{format_name} ({channel_name})",
                            'example': fmt.get('example_message', '')[:50] + '...',
                            'confidence': fmt.get('confidence', 0.8)
                        })
                        existing_names.add(format_name.lower())
                except Exception as e:
                    print(f"[FORMAT_TRAINER] Error saving discovered format: {e}")
                    formats_skipped.append({
                        'name': format_name,
                        'reason': str(e)
                    })
            
            return {
                'success': True,
                'formats_discovered': len(formats_discovered),
                'formats_saved': formats_saved,
                'formats_skipped': formats_skipped,
                'total_signals_found': result.get('total_signals_found', 0),
                'non_signals_count': len(result.get('non_signals', [])),
                'summary': result.get('summary', ''),
                'ai_powered': True
            }
            
        except json.JSONDecodeError as e:
            print(f"[FORMAT_TRAINER] JSON parse error in discovery: {e}")
            return {
                'success': False,
                'error': 'Failed to parse AI response',
                'formats_discovered': 0
            }
        except Exception as e:
            print(f"[FORMAT_TRAINER] Error in format discovery: {e}")
            return {
                'success': False,
                'error': str(e),
                'formats_discovered': 0
            }


_format_trainer_instance = None

def get_format_trainer() -> FormatTrainer:
    """Get singleton instance of FormatTrainer."""
    global _format_trainer_instance
    if _format_trainer_instance is None:
        _format_trainer_instance = FormatTrainer()
    return _format_trainer_instance
