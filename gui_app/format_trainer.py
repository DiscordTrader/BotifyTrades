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


class FormatTrainer:
    """Service for learning and applying signal formats using AI."""
    
    def __init__(self):
        self._openai_client = None
        self._openai_available = None
    
    def _get_openai_client(self):
        """Get OpenAI client, lazy initialization.
        
        Supports both Replit AI Integrations (no API key needed, billed to credits)
        and user-provided OpenAI API key (from environment or database).
        """
        if self._openai_client is not None:
            return self._openai_client
        
        if self._openai_available is False:
            return None
        
        try:
            # Check for Replit AI Integrations first (preferred - no API key needed)
            ai_integrations_key = os.environ.get('AI_INTEGRATIONS_OPENAI_API_KEY')
            ai_integrations_base = os.environ.get('AI_INTEGRATIONS_OPENAI_BASE_URL')
            user_api_key = os.environ.get('OPENAI_API_KEY')
            
            # Also check database for user's OpenAI key (saved via GUI Settings)
            if not user_api_key:
                try:
                    from .config_service import load_config
                    api_keys = load_config('api_keys')
                    if api_keys and api_keys.get('openai'):
                        user_api_key = api_keys['openai']
                except Exception as e:
                    print(f"[FORMAT_TRAINER] Could not load API key from database: {e}")
            
            from openai import OpenAI
            
            if ai_integrations_key and ai_integrations_base:
                # Use Replit AI Integrations (billed to Replit credits)
                self._openai_client = OpenAI(
                    api_key=ai_integrations_key,
                    base_url=ai_integrations_base
                )
                self._openai_available = True
                self._using_ai_integrations = True
                print("[FORMAT_TRAINER] Using Replit AI Integrations for OpenAI")
                return self._openai_client
            elif user_api_key:
                # Use user's own OpenAI API key
                self._openai_client = OpenAI(api_key=user_api_key)
                self._openai_available = True
                self._using_ai_integrations = False
                print("[FORMAT_TRAINER] Using user-provided OpenAI API key")
                return self._openai_client
            else:
                self._openai_available = False
                return None
                
        except Exception as e:
            print(f"[FORMAT_TRAINER] OpenAI initialization failed: {e}")
            self._openai_available = False
            return None
    
    def is_ai_available(self) -> bool:
        """Check if OpenAI is available."""
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
            return {
                'success': False,
                'error': 'OpenAI not available. Please configure your API key in Settings.',
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
            
            response = client.chat.completions.create(
                model="gpt-4o-mini",
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
                'error': 'OpenAI not available',
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

            response = client.chat.completions.create(
                model="gpt-4o-mini",
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


_format_trainer_instance = None

def get_format_trainer() -> FormatTrainer:
    """Get singleton instance of FormatTrainer."""
    global _format_trainer_instance
    if _format_trainer_instance is None:
        _format_trainer_instance = FormatTrainer()
    return _format_trainer_instance
