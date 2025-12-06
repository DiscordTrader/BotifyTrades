"""
AI-Powered Trade Analysis Module
Provides post-trade analysis using OpenAI GPT models
"""

import os
import json
from typing import Dict, Optional, List
from datetime import datetime
from openai import OpenAI

class TradeAnalyzer:
    """Analyzes trades using AI for technical and options analysis"""
    
    def __init__(self, model: str = "gpt-4o-mini"):
        """
        Initialize the AI analyzer
        
        Args:
            model: OpenAI model to use (gpt-4o, gpt-4o-mini, etc.)
        
        Raises:
            ValueError: If API key is not found
        """
        # Try Replit AI Integrations first, fall back to standard OpenAI API key
        api_key = os.getenv("AI_INTEGRATIONS_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("AI_INTEGRATIONS_OPENAI_BASE_URL")
        
        if not api_key:
            raise ValueError(
                "OpenAI API key not found. Please either:\n"
                "  1. Enable Replit AI Integrations (on Replit), or\n"
                "  2. Set OPENAI_API_KEY environment variable (local machine)"
            )
        
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url if base_url else None
        )
        self.model = model
    
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
        """
        Analyze a trade using AI
        
        Args:
            symbol: Stock ticker
            action: BTO or STC
            price: Entry price
            quantity: Number of shares/contracts
            option_type: C or P for options (None for stocks)
            strike: Strike price for options
            expiry: Expiration date for options
        
        Returns:
            Dict with analysis results
        """
        try:
            is_option = option_type is not None
            
            # Build trade description
            if is_option:
                trade_desc = f"{action} {quantity} {symbol} ${strike}{option_type} {expiry} @${price}"
                trade_type = "options"
            else:
                trade_desc = f"{action} {quantity} {symbol} @${price}"
                trade_type = "stock"
            
            # Create analysis prompt
            prompt = self._build_analysis_prompt(
                symbol, action, price, quantity,
                option_type, strike, expiry, trade_type
            )
            
            print(f"[AI] Analyzing trade: {trade_desc}")
            
            # Call OpenAI API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert trading analyst specializing in technical analysis and options trading. Provide concise, actionable insights."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.7,
                max_tokens=800
            )
            
            analysis_text = response.choices[0].message.content
            
            # Parse and structure the analysis
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
                result.update({
                    "option_type": option_type,
                    "strike": strike,
                    "expiry": expiry
                })
            
            # Print formatted analysis
            self._print_analysis(result)
            
            return result
            
        except Exception as e:
            print(f"[AI] ⚠️  Analysis failed: {str(e)}")
            return {
                "error": str(e),
                "symbol": symbol,
                "timestamp": datetime.now().isoformat()
            }
    
    def _build_analysis_prompt(
        self,
        symbol: str,
        action: str,
        price: float,
        quantity: int,
        option_type: Optional[str],
        strike: Optional[float],
        expiry: Optional[str],
        trade_type: str
    ) -> str:
        """Build the analysis prompt for the AI"""
        
        if trade_type == "options":
            option_direction = "Call" if option_type == "C" else "Put"
            prompt = f"""Analyze this options trade:

Trade: {action} {quantity} {symbol} ${strike} {option_direction} expiring {expiry} @ ${price}/contract

Please provide:
1. **Technical Analysis**: Key support/resistance levels for {symbol}, current trend, and relevant chart patterns
2. **Options Greeks Assessment**: 
   - Expected Delta (price sensitivity)
   - Theta impact (time decay risk)
   - Implied volatility considerations
   - Overall Greeks risk profile
3. **Probability Analysis**: Likelihood of profit based on strike vs current price, time to expiration, and typical {symbol} volatility
4. **Risk/Reward**: Maximum loss, potential profit targets, and recommended stop-loss levels
5. **Key Risks**: Biggest threats to this position (earnings, volatility crush, time decay, etc.)

Format: Short, bullet-point style. Focus on actionable insights."""

        else:  # stock trade
            prompt = f"""Analyze this stock trade:

Trade: {action} {quantity} shares of {symbol} @ ${price}

Please provide:
1. **Technical Analysis**: 
   - Key support and resistance levels
   - Current trend (bullish/bearish/neutral)
   - Relevant chart patterns
2. **Price Targets**: Realistic profit targets based on technicals
3. **Stop Loss**: Recommended stop-loss level to limit downside
4. **Risk Assessment**: Key risks and catalysts that could impact this trade
5. **Trade Outlook**: Overall probability of success and expected holding period

Format: Short, bullet-point style. Focus on actionable insights."""

        return prompt
    
    def _print_analysis(self, result: Dict):
        """Print formatted analysis to console"""
        print("\n" + "="*70)
        print(f"🤖 AI TRADE ANALYSIS - {result['symbol']}")
        print("="*70)
        
        if result['trade_type'] == 'options':
            print(f"Trade: {result['action']} {result['quantity']} {result['symbol']} "
                  f"${result['strike']}{result['option_type']} {result['expiry']} "
                  f"@${result['price']}")
        else:
            print(f"Trade: {result['action']} {result['quantity']} {result['symbol']} "
                  f"@${result['price']}")
        
        print(f"Model: {result['model_used']}")
        print(f"Time: {result['timestamp']}")
        print("-"*70)
        print(result['analysis'])
        print("="*70 + "\n")


class SentimentAnalyzer:
    """Analyzes Discord channel messages for market sentiment"""
    
    def __init__(self, model: str = "gpt-4o-mini"):
        """Initialize the sentiment analyzer"""
        # Try Replit AI Integrations first, fall back to standard OpenAI API key
        api_key = os.getenv("AI_INTEGRATIONS_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("AI_INTEGRATIONS_OPENAI_BASE_URL")
        
        if not api_key:
            raise ValueError(
                "OpenAI API key not found. Please either:\n"
                "  1. Enable Replit AI Integrations (on Replit), or\n"
                "  2. Set OPENAI_API_KEY environment variable (local machine)"
            )
        
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url if base_url else None
        )
        self.model = model
        self.message_buffer: List[str] = []
    
    def add_message(self, message: str):
        """Add a message to the sentiment buffer"""
        self.message_buffer.append(message)
        
        # Keep only last 100 messages to avoid token limits
        if len(self.message_buffer) > 100:
            self.message_buffer = self.message_buffer[-100:]
    
    def analyze_sentiment(self) -> Dict:
        """Analyze accumulated messages for market sentiment"""
        if len(self.message_buffer) < 10:
            return {
                "status": "insufficient_data",
                "message": "Need at least 10 messages for sentiment analysis"
            }
        
        try:
            # Join messages
            messages_text = "\n".join(self.message_buffer[-50:])  # Last 50 messages
            
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
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a market sentiment analyst. Extract key insights from trading discussions."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
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
            
            # Print formatted sentiment
            self._print_sentiment(result)
            
            # Clear buffer after analysis
            self.message_buffer = []
            
            return result
            
        except Exception as e:
            print(f"[AI] ⚠️  Sentiment analysis failed: {str(e)}")
            return {"error": str(e)}
    
    def _print_sentiment(self, result: Dict):
        """Print formatted sentiment analysis"""
        print("\n" + "="*70)
        print("📊 MARKET SENTIMENT ANALYSIS")
        print("="*70)
        print(f"Messages Analyzed: {result['messages_analyzed']}")
        print(f"Time: {result['timestamp']}")
        print("-"*70)
        print(result['analysis'])
        print("="*70 + "\n")
