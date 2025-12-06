"""
Real-time News Service with Finnhub API Integration
Provides market news with biotech/pharma detection and intelligent caching
"""

import os
import aiohttp
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import time

class NewsService:
    """
    Fetches real-time stock news from Finnhub API with caching and biotech detection
    
    Features:
    - Real-time general market news
    - Company-specific news
    - Biotech/pharma news detection and filtering
    - TTL-based caching to minimize API calls
    - Async HTTP requests for performance
    """
    
    def __init__(self, api_key: Optional[str] = None, cache_ttl_minutes: int = 5):
        """
        Initialize NewsService
        
        Args:
            api_key: Finnhub API key (defaults to FINNHUB_API_KEY env var)
            cache_ttl_minutes: Cache time-to-live in minutes (default: 5)
        """
        self.api_key = api_key or os.getenv('FINNHUB_API_KEY', '')
        self.base_url = "https://finnhub.io/api/v1"
        self.cache_ttl = timedelta(minutes=cache_ttl_minutes)
        
        # Cache: {symbol: {'news': [...], 'timestamp': datetime, 'is_biotech': bool}}
        self.cache = {}
        
        # Biotech/pharma keywords for industry detection
        self.biotech_keywords = [
            'biotechnology', 'biopharmaceutical', 'pharmaceutical', 'drug manufacturer',
            'genetic', 'genomic', 'clinical', 'biotech', 'pharma', 'life sciences',
            'therapeutics', 'medical devices', 'diagnostics'
        ]
        
        # Healthcare sector names
        self.healthcare_sectors = ['healthcare', 'health care', 'medical']
        
        print(f"[NEWS] NewsService initialized (cache TTL: {cache_ttl_minutes}min)")
        if not self.api_key:
            print("[NEWS] ⚠️  No FINNHUB_API_KEY found - news features will be unavailable")
    
    def is_biotech_company(self, company_profile: Dict) -> bool:
        """
        Detect if a company is biotech/pharma based on profile data
        
        Args:
            company_profile: Company profile dict from Finnhub
            
        Returns:
            True if biotech/pharma, False otherwise
        """
        try:
            # Check finnancialCurrency (for profile v2)
            industry = company_profile.get('finnhubIndustry', '').lower()
            sector = company_profile.get('sector', '').lower()  
            
            # Check sector
            if any(healthcare in sector for healthcare in self.healthcare_sectors):
                # If healthcare sector, check if biotech/pharma
                if any(keyword in industry for keyword in self.biotech_keywords):
                    return True
            
            # Fallback: check industry directly
            if any(keyword in industry for keyword in self.biotech_keywords):
                return True
            
            return False
            
        except Exception as e:
            print(f"[NEWS] Error detecting biotech: {e}")
            return False
    
    async def get_company_profile(self, symbol: str, session: aiohttp.ClientSession) -> Optional[Dict]:
        """
        Fetch company profile from Finnhub
        
        Args:
            symbol: Stock ticker
            session: aiohttp session
            
        Returns:
            Company profile dict or None if error
        """
        try:
            url = f"{self.base_url}/stock/profile2"
            params = {'symbol': symbol, 'token': self.api_key}
            
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    print(f"[NEWS] Profile fetch failed for {symbol}: HTTP {resp.status}")
                    return None
                    
        except asyncio.TimeoutError:
            print(f"[NEWS] Profile fetch timeout for {symbol}")
            return None
        except Exception as e:
            print(f"[NEWS] Profile fetch error for {symbol}: {e}")
            return None
    
    async def get_company_news(self, symbol: str, session: aiohttp.ClientSession, limit: int = 5) -> List[Dict]:
        """
        Fetch company-specific news from Finnhub
        
        Args:
            symbol: Stock ticker
            session: aiohttp session
            limit: Max number of news items (default: 5)
            
        Returns:
            List of news articles
        """
        try:
            # Get news from last 7 days
            to_date = datetime.now()
            from_date = to_date - timedelta(days=7)
            
            url = f"{self.base_url}/company-news"
            params = {
                'symbol': symbol,
                'from': from_date.strftime('%Y-%m-%d'),
                'to': to_date.strftime('%Y-%m-%d'),
                'token': self.api_key
            }
            
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                if resp.status == 200:
                    news = await resp.json()
                    # Sort by datetime (most recent first) and limit
                    news = sorted(news, key=lambda x: x.get('datetime', 0), reverse=True)
                    return news[:limit] if news else []
                else:
                    print(f"[NEWS] Company news fetch failed for {symbol}: HTTP {resp.status}")
                    return []
                    
        except asyncio.TimeoutError:
            print(f"[NEWS] Company news timeout for {symbol}")
            return []
        except Exception as e:
            print(f"[NEWS] Company news error for {symbol}: {e}")
            return []
    
    async def get_general_market_news(self, session: aiohttp.ClientSession, category: str = 'general', limit: int = 3) -> List[Dict]:
        """
        Fetch general market news from Finnhub
        
        Args:
            session: aiohttp session
            category: News category (general, forex, crypto, merger)
            limit: Max number of items
            
        Returns:
            List of news articles
        """
        try:
            url = f"{self.base_url}/news"
            params = {'category': category, 'token': self.api_key}
            
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                if resp.status == 200:
                    news = await resp.json()
                    return news[:limit] if news else []
                else:
                    print(f"[NEWS] Market news fetch failed: HTTP {resp.status}")
                    return []
                    
        except asyncio.TimeoutError:
            print(f"[NEWS] Market news timeout")
            return []
        except Exception as e:
            print(f"[NEWS] Market news error: {e}")
            return []
    
    def _check_cache(self, symbol: str) -> Optional[Dict]:
        """Check if cached news is still valid"""
        if symbol in self.cache:
            cached = self.cache[symbol]
            if datetime.now() - cached['timestamp'] < self.cache_ttl:
                return cached
        return None
    
    def _format_news_item(self, item: Dict) -> Dict:
        """Format news item for display"""
        try:
            # Convert Unix timestamp to readable date
            dt = datetime.fromtimestamp(item.get('datetime', 0))
            time_str = dt.strftime('%b %d, %I:%M %p')
            
            return {
                'headline': item.get('headline', 'No headline'),
                'summary': item.get('summary', '')[:200],  # Limit summary
                'source': item.get('source', 'Unknown'),
                'url': item.get('url', ''),
                'datetime': time_str,
                'related': item.get('related', '')
            }
        except Exception as e:
            print(f"[NEWS] Format error: {e}")
            return {
                'headline': item.get('headline', 'No headline'),
                'summary': '',
                'source': 'Unknown',
                'url': '',
                'datetime': 'Unknown',
                'related': ''
            }
    
    async def get_news(self, symbol: str, max_items: int = 5) -> Tuple[List[Dict], bool]:
        """
        Get news for a symbol with biotech detection
        
        Args:
            symbol: Stock ticker
            max_items: Max number of news items to return
            
        Returns:
            Tuple of (news_list, is_biotech)
        """
        if not self.api_key:
            print("[NEWS] No API key - skipping news fetch")
            return [], False
        
        # Check cache first
        cached = self._check_cache(symbol)
        if cached:
            print(f"[NEWS] Cache hit for {symbol}")
            return cached['news'], cached['is_biotech']
        
        print(f"[NEWS] Fetching news for {symbol}...")
        
        try:
            async with aiohttp.ClientSession() as session:
                # Fetch company profile and news in parallel
                profile_task = self.get_company_profile(symbol, session)
                company_news_task = self.get_company_news(symbol, session, limit=max_items)
                
                profile, company_news = await asyncio.gather(profile_task, company_news_task)
                
                # Detect if biotech
                is_biotech = False
                if profile:
                    is_biotech = self.is_biotech_company(profile)
                    if is_biotech:
                        print(f"[NEWS] {symbol} identified as biotech/pharma")
                
                # Format news items
                formatted_news = [self._format_news_item(item) for item in company_news]
                
                # Cache results
                self.cache[symbol] = {
                    'news': formatted_news,
                    'timestamp': datetime.now(),
                    'is_biotech': is_biotech
                }
                
                return formatted_news, is_biotech
                
        except Exception as e:
            print(f"[NEWS] Error fetching news for {symbol}: {e}")
            import traceback
            traceback.print_exc()
            return [], False
    
    def format_news_for_discord(self, news: List[Dict], is_biotech: bool, max_chars: int = 800) -> str:
        """
        Format news for Discord display
        
        Args:
            news: List of news items
            is_biotech: Whether this is a biotech stock
            max_chars: Maximum characters for Discord message
            
        Returns:
            Formatted news string
        """
        if not news:
            return "📰 **Latest News:** No recent news available\n"
        
        biotech_tag = " 💊 (Biotech/Pharma)" if is_biotech else ""
        lines = [f"📰 **Latest News**{biotech_tag}:"]
        
        total_chars = len(lines[0])
        
        for i, item in enumerate(news[:5], 1):
            # Format: "1. [Source] Headline (Time)"
            headline = item['headline'][:100]  # Truncate long headlines
            source = item['source']
            time_str = item['datetime']
            
            line = f"{i}. **[{source}]** {headline} _({time_str})_"
            
            # Check if adding this line exceeds max_chars
            if total_chars + len(line) + 2 > max_chars:
                lines.append(f"_...and {len(news) - i + 1} more_")
                break
            
            lines.append(line)
            total_chars += len(line) + 2  # +2 for newline
        
        return '\n'.join(lines)
    
    def format_news_for_ai(self, news: List[Dict], is_biotech: bool) -> str:
        """
        Format news for AI prompt context
        
        Args:
            news: List of news items
            is_biotech: Whether this is a biotech stock
            
        Returns:
            Formatted news context string
        """
        if not news:
            return "No recent news available for this stock."
        
        biotech_note = " (Note: This is a biotech/pharma company)" if is_biotech else ""
        lines = [f"Recent News Headlines{biotech_note}:"]
        
        for i, item in enumerate(news[:5], 1):
            headline = item['headline']
            source = item['source']
            summary = item['summary'][:150] if item['summary'] else "No summary"
            
            lines.append(f"{i}. [{source}] {headline}")
            if summary and summary != "No summary":
                lines.append(f"   Summary: {summary}")
        
        return '\n'.join(lines)
