"""
Swing Trading Analysis Module
Comprehensive technical analysis for high-confidence trade setups
"""

import yfinance as yf
import pandas as pd
import numpy as np
from ta.trend import MACD, EMAIndicator, SMAIndicator
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands, KeltnerChannel, AverageTrueRange
from ta.volume import VolumeWeightedAveragePrice
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta

class SwingTradeAnalyzer:
    """Comprehensive swing trading analysis with multi-indicator confluence"""
    
    def __init__(self):
        self.lookback_days = 100
        
    def analyze_symbol(self, symbol: str, timeframe: str = "1d") -> Dict:
        """
        Perform comprehensive swing trading analysis
        
        Args:
            symbol: Stock ticker
            timeframe: Analysis timeframe (1d, 4h, 1h)
        
        Returns:
            Dict with full analysis and confidence score
        """
        try:
            # Fetch price data
            df = self._fetch_data(symbol, timeframe)
            if df is None or len(df) < 50:
                return {"error": "Insufficient data for analysis"}
            
            # Calculate all indicators
            indicators = self._calculate_indicators(df)
            
            # Perform analysis
            analysis = {
                "symbol": symbol,
                "timeframe": timeframe,
                "current_price": float(df['Close'].iloc[-1]),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                
                # Trend Analysis
                "trend": self._analyze_trend(df, indicators),
                
                # Volume Analysis
                "volume": self._analyze_volume(df, indicators),
                
                # Technical Indicators
                "rsi": self._analyze_rsi(indicators),
                "macd": self._analyze_macd(indicators),
                "bollinger": self._analyze_bollinger(df, indicators),
                "moving_averages": self._analyze_mas(df, indicators),
                
                # Support/Resistance
                "support_resistance": self._find_support_resistance(df),
                
                # TTM Squeeze (custom calculation)
                "ttm_squeeze": self._analyze_ttm_squeeze(df, indicators),
                
                # Overall confluence
                "confluence": {},
                "confidence_score": 0,
                "recommendation": ""
            }
            
            # Calculate confluence and confidence
            analysis["confluence"] = self._calculate_confluence(analysis)
            analysis["confidence_score"] = self._calculate_confidence(analysis)
            analysis["recommendation"] = self._generate_recommendation(analysis)
            
            return analysis
            
        except Exception as e:
            return {"error": f"Analysis failed: {str(e)}"}
    
    def _fetch_data(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        """Fetch OHLCV data using yfinance"""
        try:
            # Map timeframe to yfinance interval
            # CRITICAL: yfinance intraday data (1h, 1m, etc) limited to 60 days max
            interval_map = {
                "1min": "1m", "5min": "5m", "15min": "15m",
                "30min": "30m", "1h": "1h", "4h": "1h",
                "1d": "1d", "1day": "1d"
            }
            
            interval = interval_map.get(timeframe, "1d")
            
            # Set period based on interval - intraday data limited to 60 days
            # This fixes the bug where 4h (mapped to 1h) was trying to fetch 1y of data
            if interval in ["1m", "5m", "15m", "30m", "1h"]:
                period = "60d"
            else:
                period = "1y"
            
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)
            
            if df.empty:
                print(f"[SWING] No data available for {symbol}")
                return None
            
            # Resample 1h to 4h if needed
            if timeframe == "4h" and interval == "1h":
                print(f"[SWING] Resampling 1h → 4h for {symbol}")
                df = df.resample('4h').agg({
                    'Open': 'first',
                    'High': 'max',
                    'Low': 'min',
                    'Close': 'last',
                    'Volume': 'sum'
                }).dropna()
                
                if df.empty:
                    print(f"[SWING] ⚠️  Resampling produced empty dataset for {symbol}")
                    return None
            
            print(f"[SWING] ✓ Fetched {len(df)} {timeframe} candles for {symbol}")
            return df
            
        except Exception as e:
            print(f"[SWING] ✗ Failed to fetch data for {symbol}: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _calculate_indicators(self, df: pd.DataFrame) -> Dict:
        """Calculate all technical indicators"""
        indicators = {}
        
        # RSI
        rsi = RSIIndicator(close=df['Close'], window=14)
        indicators['rsi'] = rsi.rsi()
        
        # MACD
        macd = MACD(close=df['Close'])
        indicators['macd'] = macd.macd()
        indicators['macd_signal'] = macd.macd_signal()
        indicators['macd_diff'] = macd.macd_diff()
        
        # Bollinger Bands
        bb = BollingerBands(close=df['Close'], window=20, window_dev=2)
        indicators['bb_upper'] = bb.bollinger_hband()
        indicators['bb_middle'] = bb.bollinger_mavg()
        indicators['bb_lower'] = bb.bollinger_lband()
        indicators['bb_width'] = bb.bollinger_wband()
        
        # Keltner Channels (for TTM Squeeze)
        kc = KeltnerChannel(high=df['High'], low=df['Low'], close=df['Close'], window=20)
        indicators['kc_upper'] = kc.keltner_channel_hband()
        indicators['kc_lower'] = kc.keltner_channel_lband()
        
        # Moving Averages
        indicators['ema_8'] = EMAIndicator(close=df['Close'], window=8).ema_indicator()
        indicators['ema_21'] = EMAIndicator(close=df['Close'], window=21).ema_indicator()
        indicators['sma_50'] = SMAIndicator(close=df['Close'], window=50).sma_indicator()
        indicators['sma_200'] = SMAIndicator(close=df['Close'], window=200).sma_indicator()
        
        # ATR (for volatility)
        atr = AverageTrueRange(high=df['High'], low=df['Low'], close=df['Close'], window=14)
        indicators['atr'] = atr.average_true_range()
        
        # VWAP
        if 'Volume' in df.columns:
            indicators['vwap'] = VolumeWeightedAveragePrice(
                high=df['High'], low=df['Low'], close=df['Close'], volume=df['Volume']
            ).volume_weighted_average_price()
        
        return indicators
    
    def _analyze_trend(self, df: pd.DataFrame, indicators: Dict) -> Dict:
        """Analyze overall trend using multiple timeframes"""
        current_price = df['Close'].iloc[-1]
        
        # MA alignment
        mas = {
            'ema_8': indicators['ema_8'].iloc[-1],
            'ema_21': indicators['ema_21'].iloc[-1],
            'sma_50': indicators['sma_50'].iloc[-1],
            'sma_200': indicators['sma_200'].iloc[-1]
        }
        
        # Determine trend
        if current_price > mas['sma_200'] and mas['sma_50'] > mas['sma_200']:
            trend_direction = "STRONG UPTREND"
            trend_score = 10
        elif current_price > mas['sma_50']:
            trend_direction = "UPTREND"
            trend_score = 7
        elif current_price < mas['sma_200'] and mas['sma_50'] < mas['sma_200']:
            trend_direction = "STRONG DOWNTREND"
            trend_score = 1
        elif current_price < mas['sma_50']:
            trend_direction = "DOWNTREND"
            trend_score = 3
        else:
            trend_direction = "SIDEWAYS"
            trend_score = 5
        
        return {
            "direction": trend_direction,
            "score": trend_score,
            "mas": mas,
            "price_above_200ma": current_price > mas['sma_200'],
            "price_above_50ma": current_price > mas['sma_50']
        }
    
    def _analyze_volume(self, df: pd.DataFrame, indicators: Dict) -> Dict:
        """Analyze volume patterns"""
        if 'Volume' not in df.columns:
            return {"error": "Volume data unavailable"}
        
        current_vol = df['Volume'].iloc[-1]
        avg_vol_20 = df['Volume'].rolling(20).mean().iloc[-1]
        avg_vol_50 = df['Volume'].rolling(50).mean().iloc[-1]
        
        vol_ratio = current_vol / avg_vol_20 if avg_vol_20 > 0 else 0
        
        # Volume scoring
        if vol_ratio > 2.0:
            volume_signal = "VERY HIGH"
            volume_score = 10
        elif vol_ratio > 1.5:
            volume_signal = "HIGH"
            volume_score = 8
        elif vol_ratio > 1.0:
            volume_signal = "ABOVE AVERAGE"
            volume_score = 6
        elif vol_ratio > 0.7:
            volume_signal = "AVERAGE"
            volume_score = 5
        else:
            volume_signal = "LOW"
            volume_score = 2
        
        return {
            "current": int(current_vol),
            "avg_20d": int(avg_vol_20),
            "ratio": round(vol_ratio, 2),
            "signal": volume_signal,
            "score": volume_score
        }
    
    def _analyze_rsi(self, indicators: Dict) -> Dict:
        """Analyze RSI with divergence detection"""
        current_rsi = indicators['rsi'].iloc[-1]
        prev_rsi = indicators['rsi'].iloc[-5:].tolist()
        
        # RSI zones
        if current_rsi > 70:
            zone = "OVERBOUGHT"
            score = 3
        elif current_rsi > 60:
            zone = "STRONG"
            score = 8
        elif current_rsi > 50:
            zone = "BULLISH"
            score = 7
        elif current_rsi > 40:
            zone = "NEUTRAL"
            score = 5
        elif current_rsi > 30:
            zone = "BEARISH"
            score = 3
        else:
            zone = "OVERSOLD"
            score = 8
        
        return {
            "current": round(current_rsi, 2),
            "zone": zone,
            "score": score,
            "oversold": current_rsi < 30,
            "overbought": current_rsi > 70
        }
    
    def _analyze_macd(self, indicators: Dict) -> Dict:
        """Analyze MACD signals"""
        macd = indicators['macd'].iloc[-1]
        signal = indicators['macd_signal'].iloc[-1]
        histogram = indicators['macd_diff'].iloc[-1]
        prev_histogram = indicators['macd_diff'].iloc[-2]
        
        # MACD signals
        if histogram > 0 and prev_histogram < 0:
            macd_signal = "BULLISH CROSSOVER"
            score = 9
        elif histogram < 0 and prev_histogram > 0:
            macd_signal = "BEARISH CROSSOVER"
            score = 2
        elif histogram > 0 and histogram > prev_histogram:
            macd_signal = "BULLISH MOMENTUM"
            score = 8
        elif histogram < 0 and histogram < prev_histogram:
            macd_signal = "BEARISH MOMENTUM"
            score = 3
        elif histogram > 0:
            macd_signal = "BULLISH"
            score = 6
        else:
            macd_signal = "BEARISH"
            score = 4
        
        return {
            "macd": round(macd, 4),
            "signal_line": round(signal, 4),
            "histogram": round(histogram, 4),
            "signal": macd_signal,
            "score": score
        }
    
    def _analyze_bollinger(self, df: pd.DataFrame, indicators: Dict) -> Dict:
        """Analyze Bollinger Bands squeeze and position"""
        current_price = df['Close'].iloc[-1]
        bb_upper = indicators['bb_upper'].iloc[-1]
        bb_lower = indicators['bb_lower'].iloc[-1]
        bb_middle = indicators['bb_middle'].iloc[-1]
        bb_width = indicators['bb_width'].iloc[-1]
        
        # Historical width for squeeze detection
        avg_width = indicators['bb_width'].rolling(20).mean().iloc[-1]
        
        # Position relative to bands
        bb_percent = (current_price - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5
        
        if bb_percent > 0.9:
            position = "NEAR UPPER BAND"
            score = 7
        elif bb_percent < 0.1:
            position = "NEAR LOWER BAND"
            score = 8
        else:
            position = "MIDDLE"
            score = 5
        
        # Squeeze detection
        squeeze = bb_width < avg_width * 0.7
        
        return {
            "upper": round(bb_upper, 2),
            "middle": round(bb_middle, 2),
            "lower": round(bb_lower, 2),
            "width": round(bb_width, 4),
            "position": position,
            "squeeze": squeeze,
            "score": score
        }
    
    def _analyze_mas(self, df: pd.DataFrame, indicators: Dict) -> Dict:
        """Analyze moving average alignment"""
        current_price = df['Close'].iloc[-1]
        
        mas = {
            'ema_8': indicators['ema_8'].iloc[-1],
            'ema_21': indicators['ema_21'].iloc[-1],
            'sma_50': indicators['sma_50'].iloc[-1],
            'sma_200': indicators['sma_200'].iloc[-1]
        }
        
        # Check alignment (bullish: 8 > 21 > 50 > 200)
        bullish_alignment = (mas['ema_8'] > mas['ema_21'] > 
                            mas['sma_50'] > mas['sma_200'])
        bearish_alignment = (mas['ema_8'] < mas['ema_21'] < 
                            mas['sma_50'] < mas['sma_200'])
        
        if bullish_alignment:
            alignment = "PERFECT BULLISH"
            score = 10
        elif bearish_alignment:
            alignment = "PERFECT BEARISH"
            score = 1
        elif current_price > mas['ema_8'] > mas['ema_21']:
            alignment = "BULLISH"
            score = 7
        elif current_price < mas['ema_8'] < mas['ema_21']:
            alignment = "BEARISH"
            score = 3
        else:
            alignment = "MIXED"
            score = 5
        
        return {
            "alignment": alignment,
            "score": score,
            "values": {k: round(v, 2) for k, v in mas.items()}
        }
    
    def _find_support_resistance(self, df: pd.DataFrame) -> Dict:
        """Find key support and resistance levels"""
        current_price = df['Close'].iloc[-1]
        
        # Recent highs/lows
        recent_high = df['High'].rolling(20).max().iloc[-1]
        recent_low = df['Low'].rolling(20).min().iloc[-1]
        
        # Longer-term levels
        support_50d = df['Low'].rolling(50).min().iloc[-1]
        resistance_50d = df['High'].rolling(50).max().iloc[-1]
        
        # Distance to levels
        distance_to_resistance = ((recent_high - current_price) / current_price) * 100
        distance_to_support = ((current_price - recent_low) / current_price) * 100
        
        # Score based on proximity
        if distance_to_support < 2:
            score = 9
        elif distance_to_resistance < 2:
            score = 8
        else:
            score = 5
        
        return {
            "resistance": round(recent_high, 2),
            "support": round(recent_low, 2),
            "current_price": round(current_price, 2),
            "distance_to_resistance_pct": round(distance_to_resistance, 2),
            "distance_to_support_pct": round(distance_to_support, 2),
            "score": score
        }
    
    def _analyze_ttm_squeeze(self, df: pd.DataFrame, indicators: Dict) -> Dict:
        """
        TTM Squeeze Analysis
        Squeeze fires when Bollinger Bands are inside Keltner Channels
        """
        bb_upper = indicators['bb_upper'].iloc[-5:]
        bb_lower = indicators['bb_lower'].iloc[-5:]
        kc_upper = indicators['kc_upper'].iloc[-5:]
        kc_lower = indicators['kc_lower'].iloc[-5:]
        
        # Squeeze condition: BB inside KC
        current_squeeze = (bb_upper.iloc[-1] < kc_upper.iloc[-1] and 
                          bb_lower.iloc[-1] > kc_lower.iloc[-1])
        prev_squeeze = (bb_upper.iloc[-2] < kc_upper.iloc[-2] and 
                       bb_lower.iloc[-2] > kc_lower.iloc[-2])
        
        # Squeeze firing (transitioning from squeeze to expansion)
        squeeze_firing = prev_squeeze and not current_squeeze
        
        # Momentum direction (simplified)
        momentum = "BULLISH" if df['Close'].iloc[-1] > df['Close'].iloc[-10] else "BEARISH"
        
        if squeeze_firing:
            signal = f"SQUEEZE FIRING {momentum}"
            score = 10
        elif current_squeeze:
            signal = "IN SQUEEZE (Building Pressure)"
            score = 6
        else:
            signal = "NO SQUEEZE"
            score = 5
        
        return {
            "status": signal,
            "in_squeeze": current_squeeze,
            "firing": squeeze_firing,
            "momentum": momentum,
            "score": score if squeeze_firing else 5
        }
    
    def _calculate_confluence(self, analysis: Dict) -> Dict:
        """Calculate how many indicators agree"""
        bullish_count = 0
        bearish_count = 0
        total_indicators = 0
        
        # Count bullish signals
        if analysis['trend']['score'] >= 7:
            bullish_count += 1
        elif analysis['trend']['score'] <= 3:
            bearish_count += 1
        total_indicators += 1
        
        if analysis['volume']['score'] >= 7:
            bullish_count += 1
        total_indicators += 1
        
        if analysis['rsi']['score'] >= 7:
            bullish_count += 1
        elif analysis['rsi']['score'] <= 3:
            bearish_count += 1
        total_indicators += 1
        
        if analysis['macd']['score'] >= 7:
            bullish_count += 1
        elif analysis['macd']['score'] <= 3:
            bearish_count += 1
        total_indicators += 1
        
        if analysis['bollinger']['score'] >= 7:
            bullish_count += 1
        elif analysis['bollinger']['score'] <= 3:
            bearish_count += 1
        total_indicators += 1
        
        if analysis['moving_averages']['score'] >= 7:
            bullish_count += 1
        elif analysis['moving_averages']['score'] <= 3:
            bearish_count += 1
        total_indicators += 1
        
        if analysis['ttm_squeeze']['score'] >= 9:
            bullish_count += 1
        total_indicators += 1
        
        return {
            "bullish_signals": bullish_count,
            "bearish_signals": bearish_count,
            "total_indicators": total_indicators,
            "bullish_percentage": round((bullish_count / total_indicators) * 100, 1),
            "bearish_percentage": round((bearish_count / total_indicators) * 100, 1)
        }
    
    def _calculate_confidence(self, analysis: Dict) -> int:
        """Calculate overall confidence score 0-100"""
        scores = []
        
        scores.append(analysis['trend']['score'])
        scores.append(analysis['volume']['score'])
        scores.append(analysis['rsi']['score'])
        scores.append(analysis['macd']['score'])
        scores.append(analysis['bollinger']['score'])
        scores.append(analysis['moving_averages']['score'])
        scores.append(analysis['ttm_squeeze']['score'])
        scores.append(analysis['support_resistance']['score'])
        
        # Average score (0-10) to percentage
        avg_score = sum(scores) / len(scores)
        confidence = int((avg_score / 10) * 100)
        
        return confidence
    
    def _generate_recommendation(self, analysis: Dict) -> str:
        """Generate trading recommendation"""
        confidence = analysis['confidence_score']
        confluence = analysis['confluence']
        
        if confidence >= 80 and confluence['bullish_signals'] >= 6:
            return "🔥 STRONG BUY - High confidence bullish setup"
        elif confidence >= 70 and confluence['bullish_signals'] >= 5:
            return "✅ BUY - Good bullish setup"
        elif confidence >= 60 and confluence['bullish_signals'] >= 4:
            return "⚠️ CAUTIOUS BUY - Moderate setup"
        elif confidence <= 30 and confluence['bearish_signals'] >= 5:
            return "🛑 STRONG SELL - High confidence bearish setup"
        elif confidence <= 40 and confluence['bearish_signals'] >= 4:
            return "❌ SELL - Bearish setup"
        else:
            return "⏸️ HOLD - Wait for better setup"
    
    def format_analysis_report(self, analysis: Dict) -> str:
        """Format analysis into readable Discord message"""
        if "error" in analysis:
            return f"❌ {analysis['error']}"
        
        report = f"""
📊 **SWING TRADE ANALYSIS: {analysis['symbol']}**
💰 Current Price: ${analysis['current_price']:.2f}
⏰ {analysis['timestamp']}

━━━━━━━━━━━━━━━━━━━━━━━━
**📈 TREND ANALYSIS**
Direction: {analysis['trend']['direction']}
Above 200 MA: {'✅' if analysis['trend']['price_above_200ma'] else '❌'}
Above 50 MA: {'✅' if analysis['trend']['price_above_50ma'] else '❌'}

**📊 VOLUME**
Signal: {analysis['volume']['signal']}
Ratio: {analysis['volume']['ratio']}x average

**🎯 KEY INDICATORS**
RSI: {analysis['rsi']['current']} ({analysis['rsi']['zone']})
MACD: {analysis['macd']['signal']}
Bollinger: {analysis['bollinger']['position']}
MA Alignment: {analysis['moving_averages']['alignment']}

**🔥 TTM SQUEEZE**
{analysis['ttm_squeeze']['status']}

**🎚️ SUPPORT/RESISTANCE**
Resistance: ${analysis['support_resistance']['resistance']} ({analysis['support_resistance']['distance_to_resistance_pct']:.1f}% away)
Support: ${analysis['support_resistance']['support']} ({analysis['support_resistance']['distance_to_support_pct']:.1f}% away)

━━━━━━━━━━━━━━━━━━━━━━━━
**✅ CONFLUENCE**
Bullish Signals: {analysis['confluence']['bullish_signals']}/{analysis['confluence']['total_indicators']} ({analysis['confluence']['bullish_percentage']:.0f}%)
Bearish Signals: {analysis['confluence']['bearish_signals']}/{analysis['confluence']['total_indicators']} ({analysis['confluence']['bearish_percentage']:.0f}%)

**🎯 CONFIDENCE SCORE: {analysis['confidence_score']}%**

**💡 RECOMMENDATION:**
{analysis['recommendation']}
"""
        return report.strip()
