"""
Alpaca Data Provider - Live Option Chain Data
Provides real-time option chain data with Greeks using Alpaca API
Works alongside Webull for trade execution
"""
import os
from datetime import datetime
from typing import List, Dict, Optional
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import OptionChainRequest, OptionSnapshotRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest
from alpaca.trading.enums import AssetStatus


class AlpacaDataProvider:
    """
    Provides live option chain data using Alpaca API
    - FREE with paper trading account
    - Real-time quotes with Greeks (delta, gamma, theta, vega)
    - Works independently of broker (can use with Webull execution)
    """
    
    def __init__(self, api_key: Optional[str] = None, secret_key: Optional[str] = None):
        """
        Initialize Alpaca data provider
        
        Args:
            api_key: Alpaca API key (defaults to ALPACA_API_KEY env var)
            secret_key: Alpaca secret key (defaults to ALPACA_SECRET_KEY env var)
        """
        self.api_key: str = api_key or os.getenv('ALPACA_API_KEY', '')
        self.secret_key: str = secret_key or os.getenv('ALPACA_SECRET_KEY', '')
        
        if not self.api_key or not self.secret_key:
            raise ValueError("Alpaca API credentials not found. Set ALPACA_API_KEY and ALPACA_SECRET_KEY")
            
        # Option data client for option chains (market data)
        self.client = OptionHistoricalDataClient(
            api_key=self.api_key,
            secret_key=self.secret_key
        )
        
        # Stock data client for stock prices
        self.stock_client = StockHistoricalDataClient(
            api_key=self.api_key,
            secret_key=self.secret_key
        )
        
        # Trading client for option contracts (more reliable for expirations)
        self.trading_client = TradingClient(
            api_key=self.api_key,
            secret_key=self.secret_key,
            paper=True
        )
        
        print(f"[AlpacaDataProvider] ✓ Initialized successfully")
    
    async def get_options_expiration_dates(self, symbol: str) -> List[str]:
        """
        Get all available expiration dates for a symbol using OptionChainRequest (market data API).
        This uses the full market data feed rather than the limited paper trading contracts.
        
        Args:
            symbol: Stock symbol (e.g., 'AAPL', 'SPY', 'SPX')
            
        Returns:
            List of expiration dates in YYYY-MM-DD format
        """
        import asyncio
        from datetime import date, timedelta
        
        try:
            print(f"[AlpacaDataProvider] Fetching expirations for {symbol} using OptionChainRequest (market data)", flush=True)
            
            # Use market data API's OptionChainRequest - this has complete options data
            # Unlike TradingClient with paper=True, this accesses full market data
            request = OptionChainRequest(
                underlying_symbol=symbol.upper()
            )
            
            # Execute blocking SDK call in background thread (non-blocking)
            chain_response = await asyncio.to_thread(
                self.client.get_option_chain, request
            )
            
            # Extract unique expiration dates from option chain
            all_expirations = set()
            
            # chain_response is a dict keyed by option symbol
            # Each option symbol contains expiration in the data
            if chain_response:
                print(f"[AlpacaDataProvider] Received {len(chain_response)} option contracts from market data", flush=True)
                
                for option_symbol, option_data in chain_response.items():
                    try:
                        # Parse expiration from OCC symbol format: SPY241220C00600000
                        # Format: SYMBOL + YYMMDD + C/P + strike
                        # Find where the date starts (after the underlying symbol)
                        symbol_upper = symbol.upper()
                        if option_symbol.startswith(symbol_upper):
                            date_part = option_symbol[len(symbol_upper):len(symbol_upper)+6]
                            if len(date_part) == 6 and date_part.isdigit():
                                year = 2000 + int(date_part[0:2])
                                month = int(date_part[2:4])
                                day = int(date_part[4:6])
                                exp_date = f"{year}-{month:02d}-{day:02d}"
                                all_expirations.add(exp_date)
                    except Exception as e:
                        continue
            
            # Sort chronologically
            sorted_expirations = sorted(list(all_expirations))
            print(f"[AlpacaDataProvider] Found {len(sorted_expirations)} unique expirations for {symbol}", flush=True)
            
            # Log first few expirations
            if sorted_expirations:
                print(f"[AlpacaDataProvider] First 5: {sorted_expirations[:5]}", flush=True)
            
            return sorted_expirations
            
        except Exception as e:
            print(f"[AlpacaDataProvider] Error fetching expirations for {symbol}: {e}", flush=True)
            import traceback
            traceback.print_exc()
            raise
    
    async def get_option_chain(self, symbol: str, expiry: str) -> Dict:
        """
        Get full option chain for a symbol and expiration date
        
        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            expiry: Expiration date in YYYY-MM-DD format
            
        Returns:
            Dict with 'calls' and 'puts' arrays containing option data with Greeks
        """
        try:
            print(f"[AlpacaDataProvider] Fetching option chain for {symbol} {expiry}")
            
            # OPTIMIZATION: Filter by expiration to reduce API payload
            # Convert YYYY-MM-DD to YYMMDD format for filtering
            exp_date = datetime.strptime(expiry, '%Y-%m-%d')
            exp_filter_str = exp_date.strftime('%y%m%d')
            
            # Get filtered option chain (only the specific expiration)
            request = OptionChainRequest(
                underlying_symbol=symbol.upper(),
                expiration_date=expiry  # Filter by specific expiration
            )
            
            # Execute blocking SDK call in background thread (non-blocking)
            import asyncio
            chain_data = await asyncio.to_thread(self.client.get_option_chain, request)
            
            calls = []
            puts = []
            
            # Process each contract (already filtered by API, but double-check)
            for contract_symbol, snapshot in chain_data.items():
                # Skip if not the right expiration (redundant check for safety)
                if exp_filter_str not in contract_symbol:
                    continue
                
                # Parse contract details
                try:
                    # Determine call/put from contract symbol
                    is_call = 'C' in contract_symbol.split(exp_filter_str)[1][0]
                    
                    # Extract strike price (last 8 digits / 1000)
                    strike_str = contract_symbol[-8:]
                    strike = float(strike_str) / 1000.0
                    
                    # Build option data
                    option_data = {
                        'symbol': contract_symbol,
                        'strike': strike,
                        'expiry': expiry,
                        'type': 'call' if is_call else 'put',
                        
                        # Pricing data
                        'bid': float(snapshot.latest_quote.bid_price) if snapshot.latest_quote else 0.0,
                        'ask': float(snapshot.latest_quote.ask_price) if snapshot.latest_quote else 0.0,
                        'last': float(snapshot.latest_trade.price) if snapshot.latest_trade else 0.0,
                        'mid': 0.0,  # Calculate below
                        
                        # Volume data (Trade object doesn't have volume attribute)
                        'volume': int(snapshot.latest_trade.size) if (snapshot.latest_trade and hasattr(snapshot.latest_trade, 'size')) else 0,
                        'open_interest': 0,  # Not available in snapshot
                        
                        # Greeks (from snapshot.greeks)
                        'delta': float(snapshot.greeks.delta) if snapshot.greeks else 0.0,
                        'gamma': float(snapshot.greeks.gamma) if snapshot.greeks else 0.0,
                        'theta': float(snapshot.greeks.theta) if snapshot.greeks else 0.0,
                        'vega': float(snapshot.greeks.vega) if snapshot.greeks else 0.0,
                        'rho': float(snapshot.greeks.rho) if snapshot.greeks else 0.0,
                        
                        # IV
                        'iv': float(snapshot.implied_volatility) if snapshot.implied_volatility else 0.0,
                        
                        # Option ID (use contract symbol)
                        'option_id': contract_symbol
                    }
                    
                    # Calculate mid price
                    if option_data['bid'] > 0 and option_data['ask'] > 0:
                        option_data['mid'] = round((option_data['bid'] + option_data['ask']) / 2, 2)
                    elif option_data['last'] > 0:
                        option_data['mid'] = option_data['last']
                    
                    # Add to appropriate list
                    if is_call:
                        calls.append(option_data)
                    else:
                        puts.append(option_data)
                        
                except Exception as e:
                    print(f"[AlpacaDataProvider] Warning: Error parsing {contract_symbol}: {e}")
                    continue
            
            # Sort by strike price
            calls.sort(key=lambda x: x['strike'])
            puts.sort(key=lambda x: x['strike'])
            
            # Fetch current stock price for ATM calculation
            stock_price = None
            try:
                from alpaca.data.requests import StockLatestQuoteRequest
                # Normalize symbol to uppercase for consistent ATM detection
                symbol_upper = symbol.upper()
                quote_request = StockLatestQuoteRequest(symbol_or_symbols=symbol_upper)
                quote_data = self.stock_client.get_stock_latest_quote(quote_request)
                
                if quote_data and symbol_upper in quote_data:
                    quote = quote_data[symbol_upper]
                    # Use mid-price (average of bid and ask)
                    stock_price = (quote.bid_price + quote.ask_price) / 2.0
                    print(f"[AlpacaDataProvider] Fetched {symbol_upper} stock price: ${stock_price:.2f}")
            except Exception as e:
                print(f"[AlpacaDataProvider] Warning: Could not fetch stock price for {symbol}: {e}")
            
            result = {
                'symbol': symbol.upper(),
                'expiry': expiry,
                'calls': calls,
                'puts': puts,
                'total_contracts': len(calls) + len(puts),
                'stock_price': stock_price  # Include for ATM calculation
            }
            
            print(f"[AlpacaDataProvider] Retrieved {len(calls)} calls, {len(puts)} puts for {symbol} {expiry}")
            
            return result
            
        except Exception as e:
            print(f"[AlpacaDataProvider] Error fetching option chain for {symbol} {expiry}: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def test_connection(self) -> bool:
        """Test Alpaca API connection"""
        try:
            # Try to get option chain for SPY (most liquid)
            request = OptionChainRequest(underlying_symbol="SPY")
            chain_data = self.client.get_option_chain(request)
            
            if chain_data:
                print(f"[AlpacaDataProvider] ✅ Connection test successful! Found {len(chain_data)} SPY contracts")
                return True
            else:
                print("[AlpacaDataProvider] ❌ Connection test failed - no data returned")
                return False
                
        except Exception as e:
            print(f"[AlpacaDataProvider] ❌ Connection test failed: {e}")
            import traceback
            traceback.print_exc()
            return False


# Global instance (initialized when credentials are available)
_alpaca_provider = None


def get_alpaca_provider() -> Optional[AlpacaDataProvider]:
    """Get or create global Alpaca data provider instance.
    
    Tries credentials in order:
    1. Environment variables (ALPACA_API_KEY, ALPACA_SECRET_KEY)
    2. Database settings via get_alpaca_settings() (same as main bot uses)
    """
    global _alpaca_provider
    
    if _alpaca_provider is None:
        api_key = os.getenv('ALPACA_API_KEY', '')
        secret_key = os.getenv('ALPACA_SECRET_KEY', '')
        
        if not api_key or not secret_key:
            try:
                from gui_app import database as db
                alpaca_settings = db.get_alpaca_settings()
                api_key = alpaca_settings.get('alpaca_api_key', '')
                secret_key = alpaca_settings.get('alpaca_secret_key', '')
                if api_key and secret_key:
                    print(f"[AlpacaDataProvider] ✓ Using credentials from database (same as main bot)")
                else:
                    print(f"[AlpacaDataProvider] Database returned empty credentials - api_key: {bool(api_key)}, secret: {bool(secret_key)}")
            except Exception as e:
                print(f"[AlpacaDataProvider] Could not load credentials from database: {e}")
                import traceback
                traceback.print_exc()
        
        if not api_key or not secret_key:
            print(f"[AlpacaDataProvider] Cannot initialize: No Alpaca credentials found (env vars or database)")
            return None
        
        try:
            _alpaca_provider = AlpacaDataProvider(api_key=api_key, secret_key=secret_key)
            print(f"[AlpacaDataProvider] ✓ Initialized successfully")
        except ValueError as e:
            print(f"[AlpacaDataProvider] Cannot initialize: {e}")
            return None
        except Exception as e:
            print(f"[AlpacaDataProvider] Error initializing: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    return _alpaca_provider
