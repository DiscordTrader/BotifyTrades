"""
Quick test script to verify Finnhub API for stock quotes
Run: python test_finnhub_quote.py
"""
import os
import requests

API_KEY = os.getenv('FINNHUB_API_KEY', '')

if not API_KEY:
    print("❌ FINNHUB_API_KEY not set!")
    print("\nTo set it:")
    print("1. Get free API key from: https://finnhub.io/register")
    print("2. Add FINNHUB_API_KEY to your Secrets in Replit")
    exit(1)

def get_stock_quote(symbol):
    """Get real-time stock quote from Finnhub"""
    url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={API_KEY}"
    response = requests.get(url, timeout=5)
    
    if response.status_code == 200:
        data = response.json()
        return {
            'symbol': symbol,
            'current_price': data.get('c', 0),
            'high': data.get('h', 0),
            'low': data.get('l', 0),
            'open': data.get('o', 0),
            'previous_close': data.get('pc', 0),
            'change': round(data.get('c', 0) - data.get('pc', 0), 2),
            'change_percent': round(((data.get('c', 0) - data.get('pc', 0)) / data.get('pc', 1)) * 100, 2) if data.get('pc') else 0
        }
    else:
        print(f"Error: HTTP {response.status_code}")
        return None

if __name__ == "__main__":
    print("=" * 50)
    print("FINNHUB STOCK QUOTE TEST")
    print("=" * 50)
    
    test_symbols = ['AAPL', 'SPY', 'TSLA']
    
    for symbol in test_symbols:
        quote = get_stock_quote(symbol)
        if quote:
            print(f"\n{symbol}:")
            print(f"  Current: ${quote['current_price']:.2f}")
            print(f"  Change:  ${quote['change']:+.2f} ({quote['change_percent']:+.2f}%)")
            print(f"  High/Low: ${quote['high']:.2f} / ${quote['low']:.2f}")
        else:
            print(f"\n{symbol}: Failed to fetch")
    
    print("\n" + "=" * 50)
    print("✅ Finnhub API is working!" if quote else "❌ Finnhub API test failed")
