"""
Multi-Broker Quote Aggregation Service

Industry-grade quote fetching with intelligent broker fallback.
Provides unified interface for:
- Stock price quotes
- Options chain/strikes
- Option quotes

Uses priority-based fallback across all connected brokers.
"""

import sys
import time
import asyncio
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache


class BrokerCapability(Enum):
    """Capabilities that brokers may support"""
    STOCK_QUOTE = "stock_quote"
    OPTIONS_CHAIN = "options_chain"
    OPTION_QUOTE = "option_quote"


@dataclass
class QuoteResult:
    """Standardized quote result"""
    success: bool
    price: Optional[float] = None
    broker: Optional[str] = None
    timestamp: Optional[datetime] = None
    error: Optional[str] = None


@dataclass
class OptionsChainResult:
    """Standardized options chain result"""
    success: bool
    strikes: List[float] = field(default_factory=list)
    expiries: List[str] = field(default_factory=list)
    broker: Optional[str] = None
    error: Optional[str] = None


@dataclass 
class OptionQuoteResult:
    """Standardized option quote result"""
    success: bool
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    mid: Optional[float] = None
    broker: Optional[str] = None
    error: Optional[str] = None


# Broker capability registry
BROKER_CAPABILITIES = {
    'webull': {
        BrokerCapability.STOCK_QUOTE: True,
        BrokerCapability.OPTIONS_CHAIN: True,
        BrokerCapability.OPTION_QUOTE: True,
    },
    'alpaca': {
        BrokerCapability.STOCK_QUOTE: True,
        BrokerCapability.OPTIONS_CHAIN: True,
        BrokerCapability.OPTION_QUOTE: True,
    },
    'robinhood': {
        BrokerCapability.STOCK_QUOTE: True,
        BrokerCapability.OPTIONS_CHAIN: True,
        BrokerCapability.OPTION_QUOTE: True,
    },
    'ibkr': {
        BrokerCapability.STOCK_QUOTE: True,
        BrokerCapability.OPTIONS_CHAIN: True,
        BrokerCapability.OPTION_QUOTE: True,
    },
    'tastytrade': {
        BrokerCapability.STOCK_QUOTE: True,
        BrokerCapability.OPTIONS_CHAIN: True,
        BrokerCapability.OPTION_QUOTE: True,
    },
    'schwab': {
        BrokerCapability.STOCK_QUOTE: True,
        BrokerCapability.OPTIONS_CHAIN: True,
        BrokerCapability.OPTION_QUOTE: True,
    },
}

# Default priority order for quote fetching (Webull first, then Robinhood, then Alpaca)
DEFAULT_PRIORITY = ['webull', 'robinhood', 'alpaca', 'ibkr', 'tastytrade', 'schwab']


class QuoteCache:
    """Simple TTL cache for quotes"""
    
    def __init__(self, ttl_seconds: int = 5):
        self.ttl = ttl_seconds
        self._cache: Dict[str, Tuple[Any, float]] = {}
    
    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self.ttl:
                return value
            del self._cache[key]
        return None
    
    def set(self, key: str, value: Any):
        self._cache[key] = (value, time.time())
    
    def clear(self):
        self._cache.clear()


class QuoteAggregator:
    """
    Multi-broker quote aggregation with intelligent fallback.
    
    Features:
    - Priority-based broker selection
    - Automatic fallback on failure
    - Short-TTL caching
    - Capability-aware routing
    - Timeout protection
    """
    
    def __init__(self, timeout_seconds: float = 5.0):
        self.timeout = timeout_seconds
        self.price_cache = QuoteCache(ttl_seconds=5)
        self.chain_cache = QuoteCache(ttl_seconds=30)
        self._brokers: Dict[str, Any] = {}
        self._priority = DEFAULT_PRIORITY.copy()
    
    def register_broker(self, name: str, broker_instance: Any):
        """Register a broker instance for quote fetching"""
        self._brokers[name.lower()] = broker_instance
        sys.stdout.write(f"[QUOTE_AGG] Registered broker: {name}\n")
        sys.stdout.flush()
    
    def set_priority(self, priority: List[str]):
        """Set broker priority order"""
        self._priority = [p.lower() for p in priority]
    
    def get_connected_brokers(self, capability: BrokerCapability) -> List[str]:
        """Get list of connected brokers with given capability"""
        result = []
        for broker_name in self._priority:
            if broker_name not in self._brokers:
                continue
            broker = self._brokers[broker_name]
            is_connected = getattr(broker, 'connected', False) or getattr(broker, '_logged_in', False)
            if not is_connected:
                continue
            caps = BROKER_CAPABILITIES.get(broker_name, {})
            if caps.get(capability, False):
                result.append(broker_name)
        return result
    
    def debug_broker_status(self):
        """Debug method to show broker connection status"""
        for broker_name in self._priority:
            if broker_name in self._brokers:
                broker = self._brokers[broker_name]
                is_connected = getattr(broker, 'connected', False)
                sys.stderr.write(f"[QUOTE_AGG] {broker_name}: connected={is_connected}\n")
                sys.stderr.flush()
    
    def _check_streaming_hubs(self, symbol: str) -> Optional[float]:
        try:
            from src.services.webull_data_hub import get_webull_data_hub
            hub = get_webull_data_hub()
            if hub.is_streaming():
                price = hub.get_quote_price(symbol)
                if price and price > 0:
                    return price
        except Exception:
            pass
        try:
            from src.services.schwab_data_hub import get_schwab_data_hub
            hub = get_schwab_data_hub()
            if hub.is_streaming():
                price = hub.get_quote_price(symbol)
                if price and price > 0:
                    return price
        except Exception:
            pass
        try:
            from src.services.ibkr_data_hub import get_ibkr_data_hub
            hub = get_ibkr_data_hub()
            if hub.is_streaming():
                price = hub.get_quote_price(symbol)
                if price and price > 0:
                    return price
        except Exception:
            pass
        try:
            from src.services.tastytrade_data_hub import get_tastytrade_data_hub
            hub = get_tastytrade_data_hub()
            if hub.is_streaming():
                price = hub.get_quote_price(symbol)
                if price and price > 0:
                    return price
        except Exception:
            pass
        return None

    def _check_streaming_hubs_detailed(self, symbol: str) -> Optional[dict]:
        try:
            from src.services.webull_data_hub import get_webull_data_hub
            hub = get_webull_data_hub()
            if hub.is_streaming():
                data = hub.get_quote_detailed(symbol)
                if data and (data.get('last', 0) > 0 or data.get('bid', 0) > 0):
                    return data
        except Exception:
            pass
        try:
            from src.services.schwab_data_hub import get_schwab_data_hub
            hub = get_schwab_data_hub()
            if hub.is_streaming():
                data = hub.get_quote_detailed(symbol)
                if data and (data.get('last', 0) > 0 or data.get('bid', 0) > 0):
                    return data
        except Exception:
            pass
        try:
            from src.services.ibkr_data_hub import get_ibkr_data_hub
            hub = get_ibkr_data_hub()
            if hub.is_streaming():
                data = hub.get_quote_detailed(symbol)
                if data and (data.get('last', 0) > 0 or data.get('bid', 0) > 0):
                    return data
        except Exception:
            pass
        try:
            from src.services.tastytrade_data_hub import get_tastytrade_data_hub
            hub = get_tastytrade_data_hub()
            if hub.is_streaming():
                data = hub.get_quote_detailed(symbol)
                if data and (data.get('last', 0) > 0 or data.get('bid', 0) > 0):
                    return data
        except Exception:
            pass
        return None

    def get_stock_price(self, symbol: str) -> QuoteResult:
        """
        Get current stock price with broker fallback.
        
        Tries streaming hubs first (zero API cost), then each connected broker in priority order.
        """
        cache_key = f"price:{symbol}"
        cached = self.price_cache.get(cache_key)
        if cached:
            return cached
        
        hub_price = self._check_streaming_hubs(symbol)
        if hub_price:
            result = QuoteResult(
                success=True,
                price=hub_price,
                broker='streaming_hub',
                timestamp=datetime.now()
            )
            self.price_cache.set(cache_key, result)
            return result
        
        brokers = self.get_connected_brokers(BrokerCapability.STOCK_QUOTE)
        
        errors = []
        for broker_name in brokers:
            broker = self._brokers[broker_name]
            try:
                price = self._get_price_from_broker(broker_name, broker, symbol)
                if price is not None and price > 0:
                    result = QuoteResult(
                        success=True,
                        price=price,
                        broker=broker_name,
                        timestamp=datetime.now()
                    )
                    self.price_cache.set(cache_key, result)
                    sys.stdout.write(f"[QUOTE_AGG] {symbol} = ${price:.2f} from {broker_name}\n")
                    sys.stdout.flush()
                    return result
            except Exception as e:
                errors.append(f"{broker_name}: {str(e)}")
                sys.stdout.write(f"[QUOTE_AGG] {broker_name} failed: {e}\n")
                sys.stdout.flush()
        
        return QuoteResult(
            success=False,
            error=f"All brokers failed: {'; '.join(errors)}"
        )
    
    def _get_price_from_broker(self, name: str, broker: Any, symbol: str) -> Optional[float]:
        """Get price from specific broker with adapter logic"""
        
        if name == 'webull':
            # Try _client first (selfbot_webull.py WebullBroker)
            wb_client = getattr(broker, '_client', None) or getattr(broker, 'wb', None)
            if wb_client:
                quote = wb_client.get_quote(symbol)
                if quote and 'close' in quote:
                    return float(quote['close'])
                if quote and 'last' in quote:
                    return float(quote['last'])
        
        elif name == 'alpaca':
            if hasattr(broker, 'data_client') and broker.data_client:
                from alpaca.data.requests import StockLatestQuoteRequest
                req = StockLatestQuoteRequest(symbol_or_symbols=[symbol])
                quotes = broker.data_client.get_stock_latest_quote(req)
                if symbol in quotes:
                    q = quotes[symbol]
                    if hasattr(q, 'ask_price') and hasattr(q, 'bid_price'):
                        return (float(q.ask_price) + float(q.bid_price)) / 2
        
        elif name == 'robinhood':
            if hasattr(broker, 'get_quote'):
                quote = broker.get_quote(symbol)
                if quote and 'last_trade_price' in quote:
                    return float(quote['last_trade_price'])
        
        elif name == 'ibkr':
            try:
                from src.services.ibkr_data_hub import get_ibkr_data_hub
                ibkr_hub = get_ibkr_data_hub()
                hub_price = None
                if ibkr_hub.is_streaming():
                    hub_price = ibkr_hub.get_quote_price(symbol)
                    if hub_price and hub_price > 0:
                        return float(hub_price)
                if not hub_price and ibkr_hub._loop and not ibkr_hub._loop.is_closed():
                    ibkr_hub.subscribe_symbol(symbol)
            except (ImportError, Exception):
                pass
        
        return None
    
    def get_options_chain(self, symbol: str, opt_type: str, expiry: Optional[str] = None) -> OptionsChainResult:
        """
        Get available option strikes with broker fallback.
        
        Args:
            symbol: Underlying symbol (e.g., 'QQQ')
            opt_type: 'C' for calls, 'P' for puts
            expiry: Optional expiry date in YYYY-MM-DD format
        """
        cache_key = f"chain:{symbol}:{opt_type}:{expiry or 'any'}"
        cached = self.chain_cache.get(cache_key)
        if cached:
            sys.stdout.write(f"[QUOTE_AGG] Cache hit for {symbol} options chain\n")
            sys.stdout.flush()
            return cached
        
        brokers = self.get_connected_brokers(BrokerCapability.OPTIONS_CHAIN)
        sys.stdout.write(f"[QUOTE_AGG] Getting {symbol} {opt_type} chain from brokers: {brokers}\n")
        sys.stdout.flush()
        
        errors = []
        for broker_name in brokers:
            broker = self._brokers[broker_name]
            try:
                strikes = self._get_chain_from_broker(broker_name, broker, symbol, opt_type, expiry)
                if strikes and len(strikes) > 0:
                    result = OptionsChainResult(
                        success=True,
                        strikes=sorted(strikes),
                        broker=broker_name
                    )
                    self.chain_cache.set(cache_key, result)
                    sys.stdout.write(f"[QUOTE_AGG] Found {len(strikes)} strikes from {broker_name}\n")
                    sys.stdout.flush()
                    return result
            except Exception as e:
                errors.append(f"{broker_name}: {str(e)}")
                sys.stdout.write(f"[QUOTE_AGG] {broker_name} chain failed: {e}\n")
                sys.stdout.flush()
        
        return OptionsChainResult(
            success=False,
            error=f"All brokers failed: {'; '.join(errors)}"
        )
    
    def _get_chain_from_broker(self, name: str, broker: Any, symbol: str, 
                                opt_type: str, expiry: Optional[str]) -> List[float]:
        """Get options chain from specific broker"""
        
        if name == 'webull':
            wb_client = getattr(broker, '_client', None) or getattr(broker, 'wb', None)
            if wb_client:
                options = wb_client.get_options(symbol)
                if options and 'data' in options:
                    strikes = []
                    for opt in options['data']:
                        if opt.get('optionType', '').upper().startswith(opt_type.upper()):
                            strikes.append(float(opt['strikePrice']))
                    return list(set(strikes))
        
        elif name == 'alpaca':
            return self._get_alpaca_chain(broker, symbol, opt_type, expiry)
        
        elif name == 'robinhood':
            try:
                import robin_stocks.robinhood as rh
                chain = rh.options.get_chains(symbol)
                if chain and 'expiration_dates' in chain:
                    instruments = rh.options.find_options_by_expiration(
                        [symbol], 
                        expirationDate=expiry if expiry else chain['expiration_dates'][0],
                        optionType=('call' if opt_type == 'C' else 'put')
                    )
                    if instruments:
                        return [float(i['strike_price']) for i in instruments]
            except Exception as e:
                sys.stdout.write(f"[QUOTE_AGG] Robinhood chain error: {e}\n")
                sys.stdout.flush()
        
        return []
    
    def _get_alpaca_chain(self, broker: Any, symbol: str, opt_type: str, 
                          expiry: Optional[str]) -> List[float]:
        """Get options chain from Alpaca with fallback"""
        try:
            from alpaca.trading.client import TradingClient
            from alpaca.trading.requests import GetOptionContractsRequest
            from alpaca.trading.enums import ContractType
            
            if hasattr(broker, 'api_key') and hasattr(broker, 'api_secret'):
                api_key = broker.api_key
                api_secret = broker.api_secret
            else:
                from gui_app.database import get_alpaca_settings
                settings = get_alpaca_settings()
                api_key = settings.get('alpaca_api_key')
                api_secret = settings.get('alpaca_secret_key')
            
            if not api_key or not api_secret:
                return []
            
            client = TradingClient(api_key, api_secret, paper=True)
            contract_type = ContractType.CALL if opt_type == 'C' else ContractType.PUT
            
            if expiry:
                from datetime import datetime as dt
                expiry_date = dt.strptime(expiry, '%Y-%m-%d').date()
                req = GetOptionContractsRequest(
                    underlying_symbols=[symbol],
                    type=contract_type,
                    expiration_date=expiry_date,
                    limit=100
                )
                contracts = client.get_option_contracts(req)
                
                if contracts and contracts.option_contracts:
                    return [float(c.strike_price) for c in contracts.option_contracts]
            
            req = GetOptionContractsRequest(
                underlying_symbols=[symbol],
                type=contract_type,
                limit=100
            )
            contracts = client.get_option_contracts(req)
            
            if contracts and contracts.option_contracts:
                return [float(c.strike_price) for c in contracts.option_contracts]
            
        except Exception as e:
            sys.stdout.write(f"[QUOTE_AGG] Alpaca chain error: {e}\n")
            sys.stdout.flush()
        
        return []
    
    def get_option_quote(self, symbol: str, strike: float, opt_type: str, 
                         expiry: str) -> OptionQuoteResult:
        """
        Get option quote with broker fallback.
        
        Args:
            symbol: Underlying symbol
            strike: Strike price
            opt_type: 'C' or 'P'
            expiry: Expiry date YYYY-MM-DD
        """
        cache_key = f"opt_quote:{symbol}:{strike}:{opt_type}:{expiry}"
        cached = self.price_cache.get(cache_key)
        if cached:
            return cached
        
        try:
            from src.services.webull_data_hub import get_webull_data_hub
            webull_hub = get_webull_data_hub()
            if webull_hub.is_streaming():
                try:
                    from gui_app.database import get_db
                    db_conn = get_db()
                    cursor = db_conn.execute(
                        "SELECT option_id FROM trades WHERE symbol=? AND strike=? AND call_put=? AND status='OPEN' LIMIT 1",
                        (symbol, strike, opt_type)
                    )
                    row = cursor.fetchone()
                    if row and row[0]:
                        hub_data = webull_hub.get_quote_detailed(str(row[0]))
                        if hub_data and (hub_data.get('last', 0) > 0 or hub_data.get('bid', 0) > 0):
                            bid = hub_data.get('bid', 0)
                            ask = hub_data.get('ask', 0)
                            last = hub_data.get('last', 0)
                            mid = (bid + ask) / 2 if bid > 0 and ask > 0 else last
                            result = OptionQuoteResult(
                                success=True,
                                bid=bid,
                                ask=ask,
                                last=last,
                                mid=mid,
                                broker='webull_hub'
                            )
                            self.price_cache.set(cache_key, result)
                            return result
                except Exception:
                    pass
        except Exception:
            pass

        try:
            from src.services.schwab_data_hub import get_schwab_data_hub
            schwab_hub = get_schwab_data_hub()
            if schwab_hub.is_streaming():
                from src.brokers.schwab_broker import SchwabBroker
                occ = SchwabBroker._build_option_symbol(None, symbol, expiry, strike, opt_type)
                hub_data = schwab_hub.get_quote_detailed(occ)
                if hub_data and (hub_data.get('last', 0) > 0 or hub_data.get('bid', 0) > 0):
                    bid = hub_data.get('bid', 0)
                    ask = hub_data.get('ask', 0)
                    last = hub_data.get('last', 0)
                    mid = (bid + ask) / 2 if bid > 0 and ask > 0 else last
                    result = OptionQuoteResult(
                        success=True,
                        bid=bid,
                        ask=ask,
                        last=last,
                        mid=mid,
                        broker='schwab_hub'
                    )
                    self.price_cache.set(cache_key, result)
                    return result
        except Exception:
            pass
        
        brokers = self.get_connected_brokers(BrokerCapability.OPTION_QUOTE)
        
        errors = []
        for broker_name in brokers:
            broker = self._brokers[broker_name]
            try:
                quote = self._get_option_quote_from_broker(
                    broker_name, broker, symbol, strike, opt_type, expiry
                )
                if quote and quote.success:
                    self.price_cache.set(cache_key, quote)
                    return quote
            except Exception as e:
                errors.append(f"{broker_name}: {str(e)}")
        
        return OptionQuoteResult(
            success=False,
            error=f"All brokers failed: {'; '.join(errors)}"
        )
    
    def _get_option_quote_from_broker(self, name: str, broker: Any, symbol: str,
                                       strike: float, opt_type: str, 
                                       expiry: str) -> Optional[OptionQuoteResult]:
        """Get option quote from specific broker"""
        import asyncio
        
        if name == 'webull':
            wb_client = getattr(broker, '_client', None) or getattr(broker, 'wb', None)
            if wb_client:
                options = wb_client.get_options(symbol, count=-1)
                if options and 'data' in options:
                    for opt in options['data']:
                        if (float(opt.get('strikePrice', 0)) == strike and
                            opt.get('optionType', '').upper().startswith(opt_type)):
                            bid = float(opt.get('bidPrice', 0) or 0)
                            ask = float(opt.get('askPrice', 0) or 0)
                            last = float(opt.get('lastPrice', 0) or 0)
                            mid = (bid + ask) / 2 if bid and ask else last
                            return OptionQuoteResult(
                                success=True,
                                bid=bid,
                                ask=ask,
                                last=last,
                                mid=mid,
                                broker=name
                            )
        
        elif name == 'alpaca':
            try:
                alpaca_expiry = expiry
                if '-' in expiry:
                    parts = expiry.split('-')
                    if len(parts) == 3:
                        alpaca_expiry = f"{int(parts[1])}/{int(parts[2])}"
                
                async def fetch_alpaca():
                    return await broker.get_option_quote(symbol, strike, opt_type, alpaca_expiry)
                
                try:
                    loop = asyncio.get_running_loop()
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        future = pool.submit(asyncio.run, fetch_alpaca())
                        quote = future.result(timeout=5)
                except RuntimeError:
                    quote = asyncio.run(fetch_alpaca())
                
                if quote:
                    bid = float(quote.get('bid', 0) or 0)
                    ask = float(quote.get('ask', 0) or 0)
                    mid = float(quote.get('mid', 0) or 0)
                    return OptionQuoteResult(
                        success=True,
                        bid=bid,
                        ask=ask,
                        last=mid,
                        mid=mid,
                        broker=name
                    )
            except Exception as e:
                sys.stderr.write(f"[QUOTE_AGG] Alpaca option quote error: {e}\n")
                sys.stderr.flush()
        
        elif name == 'robinhood':
            try:
                import robin_stocks.robinhood as rh
                opt_type_str = 'call' if opt_type.upper() == 'C' else 'put'
                option_data = rh.options.get_option_market_data(
                    symbol, expiry, str(strike), opt_type_str
                )
                if option_data and len(option_data) > 0:
                    opt = option_data[0]
                    if opt and isinstance(opt, dict):
                        bid = float(opt.get('bid_price', 0) or 0)
                        ask = float(opt.get('ask_price', 0) or 0)
                        last = float(opt.get('last_trade_price', 0) or 0)
                        adjusted_mark = float(opt.get('adjusted_mark_price', 0) or 0)
                        mid = adjusted_mark if adjusted_mark else ((bid + ask) / 2 if bid and ask else last)
                        return OptionQuoteResult(
                            success=True,
                            bid=bid,
                            ask=ask,
                            last=last,
                            mid=mid,
                            broker=name
                        )
            except Exception as e:
                pass
        
        return None


_aggregator_instance: Optional[QuoteAggregator] = None


def get_quote_aggregator() -> QuoteAggregator:
    """Get or create the global QuoteAggregator instance"""
    global _aggregator_instance
    if _aggregator_instance is None:
        _aggregator_instance = QuoteAggregator()
    return _aggregator_instance


def register_broker_with_aggregator(name: str, broker: Any):
    """Register a broker with the global aggregator"""
    agg = get_quote_aggregator()
    agg.register_broker(name, broker)
