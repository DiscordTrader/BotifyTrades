"""
AI-Powered Trade Analysis Module
Provides post-trade analysis using OpenAI or Claude models.
Respects the AI provider setting from Admin > Settings > AI & Market Data APIs.
"""

import os
import json
from typing import Dict, Optional, List
from datetime import datetime


try:
    from gui_app.config_service import (
        AI_PROVIDER_DEFAULT_MODELS as _PROVIDER_DEFAULT_MODELS,
        AI_PROVIDER_MODEL_PREFIXES as _PROVIDER_MODEL_PREFIXES,
    )
except ImportError:
    _PROVIDER_DEFAULT_MODELS = {
        'claude': 'claude-haiku-4-5-20251001',
        'gemini': 'gemini-2.0-flash',
        'openai': 'gpt-4o-mini',
    }
    _PROVIDER_MODEL_PREFIXES = {
        'claude': ('claude-',),
        'gemini': ('gemini-',),
        'openai': ('gpt-', 'o1', 'o3', 'o4'),
    }

def _resolve_model(provider: str) -> str:
    """Read model from ai_settings DB; validate it belongs to provider, else fall back to default."""
    try:
        from gui_app.database import get_ai_settings
        settings = get_ai_settings()
        model = settings.get('model', '')
        if model:
            prefixes = _PROVIDER_MODEL_PREFIXES.get(provider, ())
            if any(model.startswith(p) for p in prefixes):
                return model
    except Exception:
        pass
    return _PROVIDER_DEFAULT_MODELS.get(provider, 'gpt-4o-mini')


def _get_ai_client_and_model():
    """Get AI client based on provider setting. Returns (client, model, provider_name, is_anthropic)."""
    try:
        from gui_app.config_service import get_ai_provider
        provider = get_ai_provider()
    except Exception:
        provider = 'disabled'

    if provider == 'disabled':
        raise ValueError("AI is disabled in settings (Admin > Settings > AI & Market Data APIs)")

    if provider == 'claude':
        try:
            from anthropic import Anthropic
        except ImportError:
            raise ValueError("Anthropic SDK not installed (pip install anthropic)")
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            try:
                from gui_app.broker_credentials_service import get_api_keys_extended
                keys = get_api_keys_extended()
                api_key = keys.get('anthropic', '')
            except Exception:
                pass
        if not api_key:
            raise ValueError("Anthropic API key not configured")
        return Anthropic(api_key=api_key), _resolve_model('claude'), "claude", True

    if provider == 'gemini':
        try:
            from google import genai as _genai
        except ImportError:
            raise ValueError("Google GenAI SDK not installed (pip install google-genai)")
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            try:
                from gui_app.broker_credentials_service import get_api_keys_extended
                keys = get_api_keys_extended()
                api_key = keys.get('gemini', '')
            except Exception:
                pass
        if not api_key:
            raise ValueError("Gemini API key not configured")
        return _genai.Client(api_key=api_key), _resolve_model('gemini'), "gemini", False

    # provider == 'openai'
    try:
        from openai import OpenAI
    except ImportError:
        raise ValueError("OpenAI SDK not installed (pip install openai)")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        try:
            from gui_app.broker_credentials_service import get_api_keys_extended
            keys = get_api_keys_extended()
            api_key = keys.get('openai', '')
        except Exception:
            pass
    if not api_key:
        raise ValueError("OpenAI API key not configured")
    return OpenAI(api_key=api_key), _resolve_model('openai'), "openai", False


class TradeAnalyzer:
    """Analyzes trades using AI for technical and options analysis"""

    def __init__(self, model: str = "gpt-4o-mini"):
        self.client = None
        self.model = model
        self._provider = None
        self._is_anthropic = False
        try:
            self.client, resolved_model, self._provider, self._is_anthropic = _get_ai_client_and_model()
            if self._provider != 'openai' or model == 'gpt-4o-mini':
                self.model = resolved_model
            print(f"[AI] ✓ TradeAnalyzer initialized (provider={self._provider}, model={self.model})")
        except Exception as e:
            print(f"[AI] ⚠️ TradeAnalyzer init: {e}")

    def analyze_trade(
        self,
        symbol: str,
        action: str,
        price: float,
        quantity: int,
        option_type: Optional[str] = None,
        strike: Optional[float] = None,
        expiry: Optional[str] = None
    ) -> Dict:
        if not self.client:
            return {"error": "AI client not available", "symbol": symbol, "timestamp": datetime.now().isoformat()}

        try:
            is_option = option_type is not None
            trade_type = "options" if is_option else "stock"

            if is_option:
                trade_desc = f"{action} {quantity} {symbol} ${strike}{option_type} {expiry} @${price}"
            else:
                trade_desc = f"{action} {quantity} {symbol} @${price}"

            prompt = self._build_analysis_prompt(symbol, action, price, quantity, option_type, strike, expiry, trade_type)
            system_msg = "You are an expert trading analyst specializing in technical analysis and options trading. Provide concise, actionable insights."

            print(f"[AI] Analyzing trade: {trade_desc}")

            if self._provider == 'gemini':
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=f"{system_msg}\n\n{prompt}"
                )
                analysis_text = response.text
            elif self._is_anthropic:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=800,
                    temperature=0.7,
                    system=system_msg,
                    messages=[{"role": "user", "content": prompt}]
                )
                analysis_text = response.content[0].text
            else:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=800
                )
                analysis_text = response.choices[0].message.content

            result = {
                "symbol": symbol,
                "action": action,
                "price": price,
                "quantity": quantity,
                "trade_type": trade_type,
                "timestamp": datetime.now().isoformat(),
                "analysis": analysis_text,
                "model_used": self.model
            }

            if is_option:
                result.update({"option_type": option_type, "strike": strike, "expiry": expiry})

            self._print_analysis(result)
            return result

        except Exception as e:
            print(f"[AI] ⚠️ Analysis failed: {str(e)}")
            return {"error": str(e), "symbol": symbol, "timestamp": datetime.now().isoformat()}

    def _build_analysis_prompt(self, symbol, action, price, quantity, option_type, strike, expiry, trade_type):
        if trade_type == "options":
            option_direction = "Call" if option_type == "C" else "Put"
            return f"""Analyze this options trade:

Trade: {action} {quantity} {symbol} ${strike} {option_direction} expiring {expiry} @ ${price}/contract

Please provide:
1. **Technical Analysis**: Key support/resistance levels for {symbol}, current trend, and relevant chart patterns
2. **Options Greeks Assessment**: Expected Delta, Theta impact, IV considerations
3. **Probability Analysis**: Likelihood of profit based on strike vs current price
4. **Risk/Reward**: Maximum loss, potential profit targets, recommended stop-loss
5. **Key Risks**: Biggest threats (earnings, volatility crush, time decay)

Format: Short, bullet-point style. Focus on actionable insights."""
        else:
            return f"""Analyze this stock trade:

Trade: {action} {quantity} shares of {symbol} @ ${price}

Please provide:
1. **Technical Analysis**: Key support/resistance, trend, chart patterns
2. **Price Targets**: Realistic profit targets based on technicals
3. **Stop Loss**: Recommended stop-loss level
4. **Risk Assessment**: Key risks and catalysts
5. **Trade Outlook**: Overall probability and expected holding period

Format: Short, bullet-point style. Focus on actionable insights."""

    def _print_analysis(self, result: Dict):
        print("\n" + "="*70)
        print(f"🤖 AI TRADE ANALYSIS - {result['symbol']}")
        print("="*70)
        if result['trade_type'] == 'options':
            print(f"Trade: {result['action']} {result['quantity']} {result['symbol']} "
                  f"${result['strike']}{result['option_type']} {result['expiry']} @${result['price']}")
        else:
            print(f"Trade: {result['action']} {result['quantity']} {result['symbol']} @${result['price']}")
        print(f"Model: {result['model_used']}")
        print(f"Time: {result['timestamp']}")
        print("-"*70)
        print(result['analysis'])
        print("="*70 + "\n")


class SentimentAnalyzer:
    """Analyzes Discord channel messages for market sentiment"""

    def __init__(self, model: str = "gpt-4o-mini"):
        self.client = None
        self.model = model
        self._is_anthropic = False
        self.message_buffer: List[str] = []
        try:
            self.client, resolved_model, provider, self._is_anthropic = _get_ai_client_and_model()
            if provider != 'openai' or model == 'gpt-4o-mini':
                self.model = resolved_model
            print(f"[AI] ✓ SentimentAnalyzer initialized (provider={provider}, model={self.model})")
        except Exception as e:
            print(f"[AI] ⚠️ SentimentAnalyzer init: {e}")

    def add_message(self, message: str):
        self.message_buffer.append(message)
        if len(self.message_buffer) > 100:
            self.message_buffer = self.message_buffer[-100:]

    def analyze_sentiment(self) -> Dict:
        if len(self.message_buffer) < 10:
            return {"status": "insufficient_data", "message": "Need at least 10 messages for sentiment analysis"}

        if not self.client:
            return {"error": "AI client not available"}

        try:
            messages_text = "\n".join(self.message_buffer[-50:])
            system_msg = "You are a market sentiment analyst. Extract key insights from trading discussions."
            prompt = f"""Analyze these recent trading channel messages for market sentiment:

{messages_text}

Provide:
1. **Most Discussed Stocks**: Top 5 stocks mentioned with frequency
2. **Overall Sentiment**: Bullish, Bearish, or Neutral (with confidence %)
3. **Market Pulse**: Key themes and what traders are focused on
4. **Notable Patterns**: Any recurring trading strategies or setups mentioned
5. **Contrarian Indicators**: Any signs of extreme sentiment that might signal reversal

Keep it concise and actionable."""

            print("[AI] Analyzing market sentiment...")

            if self._provider == 'gemini':
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=f"{system_msg}\n\n{prompt}"
                )
                analysis = response.text
            elif self._is_anthropic:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=600,
                    temperature=0.7,
                    system=system_msg,
                    messages=[{"role": "user", "content": prompt}]
                )
                analysis = response.content[0].text
            else:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=600
                )
                analysis = response.choices[0].message.content

            result = {
                "timestamp": datetime.now().isoformat(),
                "messages_analyzed": len(self.message_buffer),
                "analysis": analysis,
                "model_used": self.model
            }
            self._print_sentiment(result)
            self.message_buffer = []
            return result

        except Exception as e:
            print(f"[AI] ⚠️ Sentiment analysis failed: {str(e)}")
            return {"error": str(e)}

    def _print_sentiment(self, result: Dict):
        print("\n" + "="*70)
        print("📊 MARKET SENTIMENT ANALYSIS")
        print("="*70)
        print(f"Messages Analyzed: {result['messages_analyzed']}")
        print(f"Time: {result['timestamp']}")
        print("-"*70)
        print(result['analysis'])
        print("="*70 + "\n")
