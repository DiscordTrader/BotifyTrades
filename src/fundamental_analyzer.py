"""
Fundamental Analysis Module for Stock Analysis
Fetches and formats fundamental data for long-term investment analysis
"""

import yfinance as yf
from typing import Dict, Optional, Any


class FundamentalAnalyzer:
    """Fetches and analyzes fundamental stock data for long-term insights"""
    
    def __init__(self):
        pass
    
    def get_fundamentals(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch fundamental data for a stock symbol
        
        Args:
            symbol: Stock ticker symbol
            
        Returns:
            Dictionary with fundamental metrics, or empty dict if unavailable
        """
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            # Extract key fundamental metrics
            fundamentals = {
                # Valuation
                'market_cap': info.get('marketCap'),
                'pe_ratio': info.get('trailingPE'),
                'forward_pe': info.get('forwardPE'),
                'peg_ratio': info.get('trailingPegRatio'),
                'price_to_sales': info.get('priceToSalesTrailing12Months'),
                'price_to_book': info.get('priceToBook'),
                
                # Profitability
                'profit_margin': info.get('profitMargins'),
                'operating_margin': info.get('operatingMargins'),
                'gross_margin': info.get('grossMargins'),
                'roe': info.get('returnOnEquity'),
                'roa': info.get('returnOnAssets'),
                
                # Growth
                'revenue_growth': info.get('revenueGrowth'),
                'earnings_growth': info.get('earningsGrowth'),
                'earnings_quarterly_growth': info.get('earningsQuarterlyGrowth'),
                
                # Financial Health
                'debt_to_equity': info.get('debtToEquity'),
                'current_ratio': info.get('currentRatio'),
                'quick_ratio': info.get('quickRatio'),
                'total_debt': info.get('totalDebt'),
                'total_cash': info.get('totalCash'),
                
                # Earnings & Revenue
                'total_revenue': info.get('totalRevenue'),
                'revenue_per_share': info.get('revenuePerShare'),
                'eps_trailing': info.get('trailingEps'),
                'eps_forward': info.get('forwardEps'),
                
                # Dividend
                'dividend_yield': info.get('dividendYield'),
                'dividend_rate': info.get('dividendRate'),
                'payout_ratio': info.get('payoutRatio'),
                
                # Analyst Recommendations
                'target_high_price': info.get('targetHighPrice'),
                'target_low_price': info.get('targetLowPrice'),
                'target_mean_price': info.get('targetMeanPrice'),
                'recommendation': info.get('recommendationKey'),
                'num_analyst_opinions': info.get('numberOfAnalystOpinions'),
                
                # Company Info
                'sector': info.get('sector'),
                'industry': info.get('industry'),
                'full_time_employees': info.get('fullTimeEmployees'),
                
                # Current Price
                'current_price': info.get('currentPrice') or info.get('regularMarketPrice'),
            }
            
            return fundamentals
            
        except Exception as e:
            print(f"[FUNDAMENTAL] Error fetching fundamentals for {symbol}: {e}")
            return {}
    
    def format_fundamentals_for_discord(self, fundamentals: Dict[str, Any], max_chars: int = 800) -> str:
        """
        Format fundamental data for Discord display
        
        Args:
            fundamentals: Dictionary of fundamental metrics
            max_chars: Maximum character limit
            
        Returns:
            Formatted string for Discord
        """
        if not fundamentals or not any(fundamentals.values()):
            return ""
        
        lines = []
        
        # Helper function to format numbers
        def fmt_num(val, prefix='', suffix='', decimals=2):
            if val is None:
                return "N/A"
            if abs(val) >= 1e12:
                return f"{prefix}{val/1e12:.{decimals}f}T{suffix}"
            elif abs(val) >= 1e9:
                return f"{prefix}{val/1e9:.{decimals}f}B{suffix}"
            elif abs(val) >= 1e6:
                return f"{prefix}{val/1e6:.{decimals}f}M{suffix}"
            elif abs(val) >= 1e3:
                return f"{prefix}{val/1e3:.{decimals}f}K{suffix}"
            else:
                return f"{prefix}{val:.{decimals}f}{suffix}"
        
        def fmt_pct(val):
            if val is None:
                return "N/A"
            return f"{val*100:.1f}%"
        
        # Valuation Metrics
        if any([fundamentals.get('market_cap'), fundamentals.get('pe_ratio')]):
            lines.append("**📈 Valuation:**")
            if fundamentals.get('market_cap'):
                lines.append(f"  • Market Cap: {fmt_num(fundamentals['market_cap'], '$')}")
            if fundamentals.get('pe_ratio'):
                lines.append(f"  • P/E Ratio: {fundamentals['pe_ratio']:.2f}")
            if fundamentals.get('forward_pe'):
                lines.append(f"  • Forward P/E: {fundamentals['forward_pe']:.2f}")
            if fundamentals.get('peg_ratio'):
                lines.append(f"  • PEG Ratio: {fundamentals['peg_ratio']:.2f}")
        
        # Growth Metrics
        if any([fundamentals.get('revenue_growth'), fundamentals.get('earnings_growth')]):
            lines.append("\n**📊 Growth:**")
            if fundamentals.get('revenue_growth'):
                lines.append(f"  • Revenue Growth: {fmt_pct(fundamentals['revenue_growth'])}")
            if fundamentals.get('earnings_growth'):
                lines.append(f"  • Earnings Growth: {fmt_pct(fundamentals['earnings_growth'])}")
        
        # Profitability
        if any([fundamentals.get('profit_margin'), fundamentals.get('roe')]):
            lines.append("\n**💰 Profitability:**")
            if fundamentals.get('profit_margin'):
                lines.append(f"  • Profit Margin: {fmt_pct(fundamentals['profit_margin'])}")
            if fundamentals.get('roe'):
                lines.append(f"  • ROE: {fmt_pct(fundamentals['roe'])}")
        
        # Financial Health
        if any([fundamentals.get('debt_to_equity'), fundamentals.get('current_ratio')]):
            lines.append("\n**🏦 Financial Health:**")
            if fundamentals.get('debt_to_equity'):
                lines.append(f"  • Debt/Equity: {fundamentals['debt_to_equity']:.2f}")
            if fundamentals.get('current_ratio'):
                lines.append(f"  • Current Ratio: {fundamentals['current_ratio']:.2f}")
        
        # Analyst Target
        if fundamentals.get('target_mean_price'):
            lines.append("\n**🎯 Analyst Target:**")
            current = fundamentals.get('current_price')
            target = fundamentals['target_mean_price']
            if current:
                upside = ((target - current) / current) * 100
                lines.append(f"  • Target: ${target:.2f} ({upside:+.1f}% upside)")
            else:
                lines.append(f"  • Target: ${target:.2f}")
            if fundamentals.get('recommendation'):
                lines.append(f"  • Rating: {fundamentals['recommendation'].upper()}")
        
        result = "\n".join(lines)
        
        # Truncate if too long
        if len(result) > max_chars:
            result = result[:max_chars-3] + "..."
        
        return result
    
    def format_fundamentals_for_ai(self, fundamentals: Dict[str, Any]) -> str:
        """
        Format fundamental data for AI prompt
        
        Args:
            fundamentals: Dictionary of fundamental metrics
            
        Returns:
            Formatted string for AI analysis
        """
        if not fundamentals or not any(fundamentals.values()):
            return ""
        
        lines = ["**Fundamental Data:**"]
        
        # Helper functions
        def fmt(val, suffix=''):
            if val is None:
                return "N/A"
            return f"{val:.2f}{suffix}"
        
        def fmt_pct(val):
            """Format percentage values (converts 0.18 to 18%)"""
            if val is None:
                return "N/A"
            return f"{val*100:.1f}%"
        
        def fmt_large(val):
            if val is None:
                return "N/A"
            if abs(val) >= 1e9:
                return f"${val/1e9:.2f}B"
            elif abs(val) >= 1e6:
                return f"${val/1e6:.2f}M"
            return f"${val:,.0f}"
        
        # Valuation
        lines.append(f"- Market Cap: {fmt_large(fundamentals.get('market_cap'))}")
        lines.append(f"- P/E Ratio: {fmt(fundamentals.get('pe_ratio'))}, Forward P/E: {fmt(fundamentals.get('forward_pe'))}")
        lines.append(f"- PEG Ratio: {fmt(fundamentals.get('peg_ratio'))}")
        
        # Growth
        lines.append(f"- Revenue Growth: {fmt_pct(fundamentals.get('revenue_growth'))}")
        lines.append(f"- Earnings Growth: {fmt_pct(fundamentals.get('earnings_growth'))}")
        
        # Profitability
        lines.append(f"- Profit Margin: {fmt_pct(fundamentals.get('profit_margin'))}")
        lines.append(f"- ROE: {fmt_pct(fundamentals.get('roe'))}")
        
        # Financial Health
        lines.append(f"- Debt/Equity: {fmt(fundamentals.get('debt_to_equity'))}")
        lines.append(f"- Current Ratio: {fmt(fundamentals.get('current_ratio'))}")
        
        # Analyst Data
        if fundamentals.get('target_mean_price'):
            current = fundamentals.get('current_price')
            target = fundamentals['target_mean_price']
            if current:
                upside = ((target - current) / current) * 100
                lines.append(f"- Analyst Target: ${target:.2f} ({upside:+.1f}% upside from current price)")
            lines.append(f"- Analyst Recommendation: {fundamentals.get('recommendation', 'N/A').upper()}")
        
        return "\n".join(lines)
