import os
import requests
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import traceback

class AlphaVantageScanner:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('ALPHA_VANTAGE_API_KEY')
        self.base_url = "https://www.alphavantage.co/query"
        
        if not self.api_key:
            raise ValueError("Alpha Vantage API key not found. Set ALPHA_VANTAGE_API_KEY environment variable.")
        
        print(f"[ALPHA VANTAGE] Scanner initialized with API key: {self.api_key[:8]}...")
    
    def get_options_chain(self, symbol: str) -> Optional[Dict]:
        """
        Fetch options chain for a symbol from Alpha Vantage.
        Returns raw options data including contracts, Greeks, volume, OI.
        """
        try:
            params = {
                'function': 'HISTORICAL_OPTIONS',
                'symbol': symbol.upper(),
                'apikey': self.api_key
            }
            
            print(f"[ALPHA VANTAGE] Fetching options chain for {symbol}...")
            response = requests.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            # Check for API errors
            if 'Error Message' in data:
                print(f"[ALPHA VANTAGE] API Error: {data['Error Message']}")
                return None
            
            if 'Note' in data:
                print(f"[ALPHA VANTAGE] API Note (rate limit): {data['Note']}")
                return None
            
            if 'data' not in data:
                print(f"[ALPHA VANTAGE] No options data found for {symbol}")
                return None
            
            print(f"[ALPHA VANTAGE] ✓ Retrieved {len(data['data'])} option contracts for {symbol}")
            return data
            
        except requests.exceptions.RequestException as e:
            print(f"[ALPHA VANTAGE] Request error: {e}")
            return None
        except Exception as e:
            print(f"[ALPHA VANTAGE] Error fetching options: {e}")
            traceback.print_exc()
            return None
    
    def scan_unusual_activity(
        self,
        symbols: List[str],
        min_premium: float = 100000,
        min_volume: int = 100,
        min_dte: int = 7,
        max_dte: int = 45,
        sentiment: Optional[str] = None,
        max_results: int = 10
    ) -> List[Dict]:
        """
        Scan for unusual options activity across multiple symbols.
        
        Args:
            symbols: List of stock symbols to scan
            min_premium: Minimum premium (volume * price) in dollars
            min_volume: Minimum volume threshold
            min_dte: Minimum days to expiration
            max_dte: Maximum days to expiration
            sentiment: Filter by 'bullish' (calls) or 'bearish' (puts), or None for both
            max_results: Maximum number of results to return
        
        Returns:
            List of unusual option contracts sorted by score
        """
        import time
        unusual_options = []
        
        for i, symbol in enumerate(symbols):
            # Rate limiting: Alpha Vantage free tier = 5 calls/minute
            # Add 12-second delay between requests (5 calls/min = 1 call per 12s)
            if i > 0:
                print(f"[ALPHA VANTAGE] Rate limit: waiting 12 seconds before next request...")
                time.sleep(12)
            try:
                data = self.get_options_chain(symbol)
                if not data or 'data' not in data:
                    continue
                
                options = data['data']
                
                for option in options:
                    try:
                        # Parse option data
                        contract_id = option.get('contractID', '')
                        option_type = option.get('type', '')
                        strike = float(option.get('strike', 0))
                        expiration = option.get('expiration', '')
                        last_price = float(option.get('last', 0))
                        bid = float(option.get('bid', 0))
                        ask = float(option.get('ask', 0))
                        volume = int(option.get('volume', 0))
                        open_interest = int(option.get('open_interest', 0))
                        implied_volatility = float(option.get('implied_volatility', 0))
                        
                        # Skip if missing critical data
                        if not all([strike, expiration, last_price, volume]):
                            continue
                        
                        # Calculate DTE
                        exp_date = datetime.strptime(expiration, '%Y-%m-%d')
                        dte = (exp_date - datetime.now()).days
                        
                        # Apply filters
                        if dte < min_dte or dte > max_dte:
                            continue
                        
                        if volume < min_volume:
                            continue
                        
                        if sentiment:
                            if sentiment.lower() == 'bullish' and option_type.lower() != 'call':
                                continue
                            if sentiment.lower() == 'bearish' and option_type.lower() != 'put':
                                continue
                        
                        # Calculate premium
                        premium = volume * last_price * 100  # Options are per 100 shares
                        
                        if premium < min_premium:
                            continue
                        
                        # Calculate unusual activity score
                        # Higher score = more unusual activity
                        volume_to_oi = volume / max(open_interest, 1)
                        unusual_score = (
                            (volume / 100) * 0.3 +  # Volume weight
                            (premium / 100000) * 0.3 +  # Premium weight
                            (volume_to_oi * 50) * 0.2 +  # Volume/OI ratio weight
                            (implied_volatility * 10) * 0.2  # IV weight
                        )
                        
                        # Calculate Greeks proxy (simplified without real-time stock price)
                        mid_price = (bid + ask) / 2 if bid and ask else last_price
                        
                        unusual_options.append({
                            'symbol': symbol,
                            'contract_id': contract_id,
                            'type': option_type,
                            'strike': strike,
                            'expiration': expiration,
                            'dte': dte,
                            'last_price': last_price,
                            'bid': bid,
                            'ask': ask,
                            'mid_price': mid_price,
                            'volume': volume,
                            'open_interest': open_interest,
                            'premium': premium,
                            'implied_volatility': implied_volatility,
                            'volume_to_oi_ratio': volume_to_oi,
                            'unusual_score': unusual_score
                        })
                        
                    except Exception as e:
                        print(f"[ALPHA VANTAGE] Error parsing option: {e}")
                        continue
                        
            except Exception as e:
                print(f"[ALPHA VANTAGE] Error scanning {symbol}: {e}")
                continue
        
        # Sort by unusual score (highest first)
        unusual_options.sort(key=lambda x: x['unusual_score'], reverse=True)
        
        # Return top results
        top_results = unusual_options[:max_results]
        
        print(f"[ALPHA VANTAGE] ✓ Found {len(unusual_options)} unusual options, returning top {len(top_results)}")
        
        return top_results
    
    def format_option_display(self, option: Dict) -> str:
        """
        Format an option for Discord display.
        """
        type_emoji = "📈" if option['type'].lower() == 'call' else "📉"
        
        return (
            f"{type_emoji} **{option['symbol']} ${option['strike']}{option['type'][0].upper()} {option['expiration']}**\n"
            f"├─ Last: ${option['last_price']:.2f} | Bid/Ask: ${option['bid']:.2f}/${option['ask']:.2f}\n"
            f"├─ Volume: {option['volume']:,} | OI: {option['open_interest']:,} | Vol/OI: {option['volume_to_oi_ratio']:.2f}x\n"
            f"├─ Premium: ${option['premium']:,.0f} | IV: {option['implied_volatility']*100:.1f}%\n"
            f"├─ DTE: {option['dte']} days\n"
            f"└─ Unusual Score: {option['unusual_score']:.1f}"
        )
    
    def scan_top_movers(self, min_price: float = 0.10, max_price: float = 5.00) -> List[Dict]:
        try:
            params = {
                'function': 'TOP_GAINERS_LOSERS',
                'apikey': self.api_key
            }
            print(f"[ALPHA VANTAGE] Fetching top movers (penny range ${min_price}-${max_price})...")
            response = requests.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if 'Error Message' in data:
                print(f"[ALPHA VANTAGE] API Error: {data['Error Message']}")
                return []
            if 'Note' in data or 'Information' in data:
                print(f"[ALPHA VANTAGE] Rate limit hit: {data.get('Note') or data.get('Information')}")
                return []

            candidates = []
            for section in ('top_gainers', 'top_losers', 'most_actively_traded'):
                for item in data.get(section, []):
                    try:
                        price = float(item.get('price', 0))
                        if price < min_price or price > max_price:
                            continue
                        candidates.append({
                            'symbol': item.get('ticker', ''),
                            'price': price,
                            'change_amount': float(item.get('change_amount', 0)),
                            'change_pct': float(item.get('change_percentage', '0').replace('%', '')),
                            'volume': int(item.get('volume', 0)),
                            'source_section': section,
                        })
                    except (ValueError, TypeError):
                        continue

            seen = set()
            unique = []
            for c in candidates:
                if c['symbol'] and c['symbol'] not in seen:
                    seen.add(c['symbol'])
                    unique.append(c)

            print(f"[ALPHA VANTAGE] ✓ Found {len(unique)} penny stock candidates in ${min_price}-${max_price} range")
            return unique

        except requests.exceptions.RequestException as e:
            print(f"[ALPHA VANTAGE] Request error: {e}")
            return []
        except Exception as e:
            print(f"[ALPHA VANTAGE] Error fetching top movers: {e}")
            traceback.print_exc()
            return []

    def test_connection(self) -> bool:
        """
        Test API connection with a simple query.
        """
        try:
            params = {
                'function': 'TIME_SERIES_INTRADAY',
                'symbol': 'SPY',
                'interval': '5min',
                'apikey': self.api_key
            }
            
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if 'Error Message' in data or 'Note' in data:
                print(f"[ALPHA VANTAGE] Connection test failed: {data}")
                return False
            
            print("[ALPHA VANTAGE] ✓ Connection test successful")
            return True
            
        except Exception as e:
            print(f"[ALPHA VANTAGE] Connection test error: {e}")
            return False


if __name__ == "__main__":
    scanner = AlphaVantageScanner()
    
    if scanner.test_connection():
        print("\n[TEST] Scanning for unusual activity in SPY...")
        results = scanner.scan_unusual_activity(
            symbols=['SPY'],
            min_premium=50000,
            min_volume=50,
            min_dte=7,
            max_dte=30,
            max_results=5
        )
        
        print(f"\n[TEST] Found {len(results)} unusual options:")
        for option in results:
            print("\n" + scanner.format_option_display(option))
