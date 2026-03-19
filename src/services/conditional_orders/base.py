"""
Base Conditional Order Service

Abstract base class with shared logic for market-specific implementations.
Each market service inherits from this and provides its own:
- Broker registry
- Rate limiters  
- Price monitor fallback chain
- Event loop/thread isolation
"""

import os
import asyncio
import aiohttp
import threading
import json
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import deque
from abc import ABC, abstractmethod

try:
    import pytz
    IST = pytz.timezone('Asia/Kolkata')
    EST = pytz.timezone('America/New_York')
except ImportError:
    IST = None
    EST = None

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from gui_app.database import (
    get_conditional_order_settings,
    save_conditional_order_settings,
    create_conditional_order,
    update_conditional_order_status,
    get_active_conditional_orders,
    get_conditional_order_by_id,
    cancel_conditional_order,
    expire_old_conditional_orders,
    get_channel_conditional_settings,
)

from gui_app.discord_notifier import (
    notify_conditional_created,
    notify_conditional_triggered,
    notify_conditional_expired,
    notify_conditional_failed,
    notify_conditional_cancelled,
)


class OrderStatus(Enum):
    PENDING = 'PENDING'
    VALIDATING = 'VALIDATING'
    PENDING_MONITOR = 'PENDING_MONITOR'
    ACTIVE_MONITORING = 'ACTIVE_MONITORING'
    FALLBACK_MONITORING = 'FALLBACK_MONITORING'
    TRIGGERED = 'TRIGGERED'
    EXECUTING = 'EXECUTING'
    TRACKING = 'TRACKING'
    TERMINATED = 'TERMINATED'
    CANCELED = 'CANCELED'
    EXPIRED = 'EXPIRED'
    ERROR = 'ERROR'


@dataclass
class RateLimitTracker:
    """Track API rate limits per broker/provider."""
    name: str
    max_calls_per_minute: int
    calls: List[float] = field(default_factory=list)
    
    def record_call(self):
        self.calls.append(datetime.now().timestamp())
        self._cleanup_old_calls()
    
    def _cleanup_old_calls(self):
        cutoff = datetime.now().timestamp() - 60
        self.calls = [c for c in self.calls if c > cutoff]
    
    def get_usage_ratio(self) -> float:
        self._cleanup_old_calls()
        return len(self.calls) / self.max_calls_per_minute if self.max_calls_per_minute > 0 else 0
    
    def can_make_call(self) -> bool:
        return self.get_usage_ratio() < 1.0
    
    def should_fallback(self, threshold: float = 0.8) -> bool:
        return self.get_usage_ratio() >= threshold


class PriceMonitor(ABC):
    """Base class for price monitoring."""
    
    def __init__(self, symbol: str, callback: Callable[[str, float], None]):
        self.symbol = symbol
        self.callback = callback
        self.is_running = False
        self.last_price = None
        self._last_price_update_time: float = 0  # Universal staleness tracking
    
    def get_staleness_seconds(self) -> int:
        """Get seconds since last successful price update."""
        if self._last_price_update_time == 0:
            return 0  # No price yet, not considered stale
        return int(time.time() - self._last_price_update_time)
    
    def _update_price_timestamp(self):
        """Update the last price update timestamp. Call after successful price fetch."""
        self._last_price_update_time = time.time()
    
    @abstractmethod
    async def start(self):
        """Start monitoring - must be implemented by subclass."""
        pass
    
    async def stop(self):
        """Stop monitoring."""
        self.is_running = False


class FinnhubPriceMonitor(PriceMonitor):
    """Price monitor using Finnhub API (US stocks)."""
    
    def __init__(self, symbol: str, callback: Callable[[str, float], None], api_key: str):
        super().__init__(symbol, callback)
        self.api_key = api_key
        self.poll_interval = 1  # 60 req/min limit - can poll every 1 second
    
    async def start(self):
        self.is_running = True
        sys.stderr.write(f"[FINNHUB] Starting price monitor for {self.symbol}\n")
        sys.stderr.flush()
        
        async with aiohttp.ClientSession() as session:
            poll_count = 0
            while self.is_running:
                try:
                    url = f"https://finnhub.io/api/v1/quote?symbol={self.symbol}&token={self.api_key}"
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            price = data.get('c')
                            poll_count += 1
                            if poll_count <= 3 or poll_count % 20 == 0:
                                sys.stderr.write(f"[FINNHUB] Poll #{poll_count} {self.symbol}: ${price}\n")
                                sys.stderr.flush()
                            if price:
                                self._update_price_timestamp()  # Track staleness
                                if price != self.last_price:
                                    self.last_price = price
                                    await self.callback(self.symbol, float(price))
                                elif poll_count % 10 == 0:
                                    # Heartbeat update - refreshes timestamp even if price unchanged
                                    await self.callback(self.symbol, float(price))
                except Exception as e:
                    sys.stderr.write(f"[FINNHUB] Error for {self.symbol}: {e}\n")
                    sys.stderr.flush()
                
                await asyncio.sleep(self.poll_interval)


class YFinancePriceMonitor(PriceMonitor):
    """Price monitor using yfinance (delayed data fallback)."""
    
    def __init__(self, symbol: str, callback: Callable[[str, float], None]):
        super().__init__(symbol, callback)
        self.poll_interval = 15
    
    async def start(self):
        self.is_running = True
        sys.stderr.write(f"[YFINANCE] Starting price monitor for {self.symbol} (delayed ~15min)\n")
        sys.stderr.flush()
        
        poll_count = 0
        while self.is_running:
            try:
                price = await self._fetch_price()
                poll_count += 1
                if poll_count <= 3 or poll_count % 10 == 0:
                    sys.stderr.write(f"[YFINANCE] Poll #{poll_count} {self.symbol}: ${price}\n")
                    sys.stderr.flush()
                if price:
                    self._update_price_timestamp()  # Track staleness
                    if price != self.last_price:
                        self.last_price = price
                        await self.callback(self.symbol, float(price))
                    elif poll_count % 10 == 0:
                        # Heartbeat update - refreshes timestamp
                        await self.callback(self.symbol, float(price))
            except Exception as e:
                sys.stderr.write(f"[YFINANCE] Error for {self.symbol}: {e}\n")
                sys.stderr.flush()
            
            await asyncio.sleep(self.poll_interval)
    
    async def _fetch_price(self) -> Optional[float]:
        if not YFINANCE_AVAILABLE:
            return None
        try:
            loop = asyncio.get_event_loop()
            def get_fast_price():
                ticker = yf.Ticker(self.symbol)
                fast_info = ticker.fast_info
                return fast_info.get('lastPrice') or fast_info.get('regularMarketPrice')
            price = await loop.run_in_executor(None, get_fast_price)
            return float(price) if price else None
        except Exception as e:
            sys.stderr.write(f"[YFINANCE] Fetch error for {self.symbol}: {e}\n")
            sys.stderr.flush()
            return None


class StreamingPriceMonitor(PriceMonitor):
    """Price monitor using WebSocket/MQTT streaming data hubs (zero API calls).
    
    Queries the data hub cache first (sub-100ms latency).
    Falls back to REST polling only if hub has no data for the symbol.
    """
    
    HUB_POLL_INTERVAL = 0.25
    REST_FALLBACK_INTERVAL = 3
    HUB_STALE_THRESHOLD = 10
    
    def __init__(self, symbol: str, callback: Callable[[str, float], None],
                 data_hub: Any, broker_name: str, broker_instance: Any = None,
                 finnhub_api_key: str = None):
        super().__init__(symbol, callback)
        self.data_hub = data_hub
        self.broker_name = broker_name
        self.broker_instance = broker_instance
        self.finnhub_api_key = finnhub_api_key
        self._hub_miss_count = 0
        self._using_rest_fallback = False
        self._rest_monitor: Optional['BrokerPriceMonitor'] = None
        self._rest_session: Optional[aiohttp.ClientSession] = None
        self._last_rest_call = 0
    
    def _try_subscribe_streaming(self):
        try:
            has_broker = self.broker_instance is not None
            has_client = has_broker and hasattr(self.broker_instance, '_streaming_client') and self.broker_instance._streaming_client is not None
            
            if not has_client:
                sys.stderr.write(f"[STREAM_MON] Cannot subscribe {self.symbol}: broker={has_broker}, streaming_client={has_client}\n")
                sys.stderr.flush()
                return False
                
            client = self.broker_instance._streaming_client
            ticker_id = None
            
            if hasattr(self.data_hub, 'get_ticker_id'):
                ticker_id = self.data_hub.get_ticker_id(self.symbol)
                
            if not ticker_id:
                try:
                    import requests as _req
                    url = f'https://quotes-gw.webullfintech.com/api/search/pc/tickers?keyword={self.symbol}&pageIndex=1&pageSize=1&regionId=6'
                    resp = _req.get(url, timeout=5)
                    data = resp.json().get('data', [])
                    for item in data:
                        if item.get('symbol', '').upper() == self.symbol.upper():
                            tid = item.get('tickerId')
                            if tid and int(tid) > 0:
                                ticker_id = str(int(tid))
                                sys.stderr.write(f"[STREAM_MON] Looked up ticker_id for {self.symbol}: {ticker_id}\n")
                                sys.stderr.flush()
                                if hasattr(self.data_hub, 'register_ticker_id'):
                                    self.data_hub.register_ticker_id(self.symbol, ticker_id)
                            break
                except Exception as e:
                    sys.stderr.write(f"[STREAM_MON] Ticker lookup error for {self.symbol}: {e}\n")
                    sys.stderr.flush()
                    
            # ── Schwab WebSocket (subscribe_equities / subscribe_options) ──
            if hasattr(client, 'subscribe_equities'):
                try:
                    import asyncio as _asyncio
                    loop = _asyncio.get_event_loop()
                    if self.symbol.count(' ') >= 1 and len(self.symbol) >= 15:
                        # Looks like an OCC option key → use subscribe_options
                        loop.create_task(client.subscribe_options([self.symbol]))
                        sys.stderr.write(f"[STREAM_MON] ✓ Schwab: subscribing option {self.symbol} to WebSocket stream\n")
                    else:
                        loop.create_task(client.subscribe_equities([self.symbol]))
                        sys.stderr.write(f"[STREAM_MON] ✓ Schwab: subscribing equity {self.symbol} to WebSocket stream\n")
                    sys.stderr.flush()
                    return True
                except Exception as e:
                    sys.stderr.write(f"[STREAM_MON] Schwab subscribe error for {self.symbol}: {e}\n")
                    sys.stderr.flush()
                return False

            # ── Webull MQTT (subscribe_symbol with ticker_id) ──────────────
            if ticker_id and str(ticker_id) != '0':
                client.subscribe_symbol(self.symbol, str(ticker_id))
                sys.stderr.write(f"[STREAM_MON] ✓ Subscribed {self.symbol} to streaming (tid={ticker_id})\n")
                sys.stderr.flush()
                return True
            else:
                sys.stderr.write(f"[STREAM_MON] No ticker_id found for {self.symbol}, cannot subscribe to streaming\n")
                sys.stderr.flush()
        except Exception as e:
            sys.stderr.write(f"[STREAM_MON] Could not subscribe {self.symbol}: {e}\n")
            sys.stderr.flush()
        return False

    async def start(self):
        self.is_running = True
        sys.stderr.write(f"[STREAM_MON] Starting streaming price monitor for {self.symbol} via {self.broker_name} hub\n")
        sys.stderr.flush()
        
        self._try_subscribe_streaming()
        
        poll_count = 0
        while self.is_running:
            try:
                price = self._query_hub()
                poll_count += 1
                
                if price:
                    self._hub_miss_count = 0
                    self._using_rest_fallback = False
                    self._update_price_timestamp()
                    
                    if poll_count <= 3 or poll_count % 40 == 0:
                        sys.stderr.write(f"[STREAM_MON] {self.symbol}: ${price:.2f} (hub, poll #{poll_count})\n")
                        sys.stderr.flush()
                    
                    now = time.time()
                    last_cb = getattr(self, '_last_callback_time', 0)
                    if price != self.last_price:
                        self.last_price = price
                        self._last_callback_time = now
                        await self.callback(self.symbol, price)
                    elif now - last_cb >= 3.0:
                        self._last_callback_time = now
                        await self.callback(self.symbol, price)
                    
                    await asyncio.sleep(self.HUB_POLL_INTERVAL)
                else:
                    self._hub_miss_count += 1
                    
                    if self._hub_miss_count >= 4 and not self._using_rest_fallback:
                        self._using_rest_fallback = True
                        sys.stderr.write(f"[STREAM_MON] Hub miss for {self.symbol} x{self._hub_miss_count}, falling back to REST\n")
                        sys.stderr.flush()
                    
                    if self._using_rest_fallback:
                        rest_price = await self._fetch_rest_price()
                        if rest_price:
                            self._update_price_timestamp()
                            self.last_price = rest_price
                            await self.callback(self.symbol, rest_price)
                        await asyncio.sleep(self.REST_FALLBACK_INTERVAL)
                    else:
                        await asyncio.sleep(self.HUB_POLL_INTERVAL)
                        
            except Exception as e:
                sys.stderr.write(f"[STREAM_MON] Error for {self.symbol}: {e}\n")
                sys.stderr.flush()
                await asyncio.sleep(1)
    
    def _query_hub(self) -> Optional[float]:
        try:
            price = self.data_hub.get_quote_price(self.symbol)
            if price and price > 0:
                return float(price)
        except Exception as e:
            sys.stderr.write(f"[STREAM_MON] Hub query error for {self.symbol}: {e}\n")
            sys.stderr.flush()
        return None
    
    async def _fetch_rest_price(self) -> Optional[float]:
        now = time.time()
        if now - self._last_rest_call < self.REST_FALLBACK_INTERVAL - 0.5:
            return self.last_price
        self._last_rest_call = now
        
        if self.broker_instance and hasattr(self.broker_instance, 'get_quote'):
            try:
                import inspect
                quote_method = self.broker_instance.get_quote
                if inspect.iscoroutinefunction(quote_method):
                    result = await quote_method(self.symbol)
                else:
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, lambda: quote_method(self.symbol))
                if isinstance(result, (int, float)) and result > 0:
                    return float(result)
                elif isinstance(result, dict):
                    for key in ('close', 'last', 'lastTradePrice', 'price', 'last_trade_price'):
                        val = result.get(key)
                        if val and float(val) > 0:
                            return float(val)
            except Exception:
                pass
        
        if self.finnhub_api_key:
            try:
                if not self._rest_session or self._rest_session.closed:
                    self._rest_session = aiohttp.ClientSession()
                url = f"https://finnhub.io/api/v1/quote?symbol={self.symbol}&token={self.finnhub_api_key}"
                async with self._rest_session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        price = data.get('c')
                        if price and float(price) > 0:
                            return float(price)
            except Exception:
                pass
        
        return None
    
    def _try_unsubscribe_streaming(self):
        try:
            if self.broker_instance and hasattr(self.broker_instance, '_streaming_client'):
                client = self.broker_instance._streaming_client
                if client and hasattr(client, 'unsubscribe_symbol'):
                    client.unsubscribe_symbol(self.symbol)
                    sys.stderr.write(f"[STREAM_MON] Unsubscribed {self.symbol} from streaming\n")
                    sys.stderr.flush()
        except Exception:
            pass

    async def stop(self):
        self.is_running = False
        self._try_unsubscribe_streaming()
        if self._rest_session and not self._rest_session.closed:
            try:
                await self._rest_session.close()
            except Exception:
                pass


class BrokerPriceMonitor(PriceMonitor):
    """Price monitor using broker API (Webull, Alpaca, Questrade, etc.)."""
    
    # Broker-specific poll intervals based on API rate limits
    BROKER_POLL_INTERVALS = {
        'alpaca': 1,      # 200 req/min limit - can poll every 1 second
        'alpaca_paper': 1,
        'alpaca_live': 1,
        'webull': 3,      # 10 req/30 sec limit - minimum 3 seconds
        'questrade': 2,   # Conservative default
        'tastytrade': 2,
        'ibkr': 1,        # No strict limit for TWS
        'schwab': 2,
        'trading212': 5,  # Portfolio-based quotes, conservative interval
    }
    
    # Stale price detection threshold
    STALE_THRESHOLD_POLLS = 10  # After 10 unchanged polls, check Finnhub
    
    def __init__(self, symbol: str, callback: Callable[[str, float], None], broker_name: str, broker_instance: Any = None, finnhub_api_key: str = None):
        super().__init__(symbol, callback)
        self.broker_name = broker_name
        self.broker_instance = broker_instance
        self.finnhub_api_key = finnhub_api_key
        # Set poll interval based on broker API limits
        broker_lower = broker_name.lower()
        self.poll_interval = self.BROKER_POLL_INTERVALS.get(broker_lower, 2)  # Default 2 sec
        # Stale price detection
        self.unchanged_count = 0
        self.using_finnhub_fallback = False
    
    HUB_FAST_INTERVAL = 0.5

    async def start(self):
        self.is_running = True
        self._hub_available = False
        sys.stderr.write(f"[{self.broker_name.upper()}] Starting price monitor for {self.symbol} (poll interval: {self.poll_interval}s, hub-accelerated: 0.5s)\n")
        sys.stderr.flush()
        
        poll_count = 0
        while self.is_running:
            try:
                price = await self._fetch_price()
                poll_count += 1
                
                if price and price == self.last_price:
                    self.unchanged_count += 1
                    if self.unchanged_count >= self.STALE_THRESHOLD_POLLS and self.finnhub_api_key and not self.using_finnhub_fallback:
                        finnhub_price = await self._fetch_finnhub_price()
                        if finnhub_price and abs(finnhub_price - price) > 0.05:
                            sys.stderr.write(f"[{self.broker_name.upper()}] STALE DATA DETECTED for {self.symbol}: broker=${price:.2f}, Finnhub=${finnhub_price:.2f}\n")
                            sys.stderr.write(f"[{self.broker_name.upper()}] Switching to Finnhub for {self.symbol}\n")
                            sys.stderr.flush()
                            self.using_finnhub_fallback = True
                            price = finnhub_price
                            self.unchanged_count = 0
                else:
                    self.unchanged_count = 0
                
                if self.using_finnhub_fallback and self.finnhub_api_key:
                    price = await self._fetch_finnhub_price() or price
                
                if poll_count <= 3 or poll_count % 10 == 0:
                    source = "FINNHUB" if self.using_finnhub_fallback else self.broker_name.upper()
                    hub_tag = " (via hub)" if self._hub_available else ""
                    sys.stderr.write(f"[{source}] Poll #{poll_count} for {self.symbol}: price={price}{hub_tag}\n")
                    sys.stderr.flush()
                
                if price:
                    self._update_price_timestamp()
                    if price != self.last_price:
                        self.last_price = price
                        await self.callback(self.symbol, price)
                    elif poll_count % 10 == 0:
                        await self.callback(self.symbol, price)
            except Exception as e:
                sys.stderr.write(f"[{self.broker_name.upper()}] Error for {self.symbol}: {e}\n")
                sys.stderr.flush()
            
            interval = self.HUB_FAST_INTERVAL if self._hub_available else self.poll_interval
            await asyncio.sleep(interval)
    
    async def _fetch_finnhub_price(self) -> Optional[float]:
        """Fetch price from Finnhub as fallback for stale broker data."""
        if not self.finnhub_api_key:
            return None
        try:
            url = f"https://finnhub.io/api/v1/quote?symbol={self.symbol}&token={self.finnhub_api_key}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        price = data.get('c')
                        return float(price) if price else None
        except Exception as e:
            sys.stderr.write(f"[FINNHUB FALLBACK] Error for {self.symbol}: {e}\n")
            sys.stderr.flush()
        return None
    
    def _try_any_streaming_hub(self) -> Optional[float]:
        """Check all available streaming/polling hubs for price data (zero extra API cost).
        Useful for brokers without their own hub (Alpaca, Robinhood, Tastytrade, etc.)."""
        for hub_getter, hub_name in [
            ('src.services.webull_data_hub', 'get_webull_data_hub'),
            ('src.services.schwab_data_hub', 'get_schwab_data_hub'),
            ('src.services.ibkr_data_hub', 'get_ibkr_data_hub'),
            ('src.services.trading212_data_hub', 'get_trading212_data_hub'),
        ]:
            try:
                import importlib
                mod = importlib.import_module(hub_getter)
                hub = getattr(mod, hub_name)()
                price = hub.get_quote_price(self.symbol)
                if price and price > 0:
                    return float(price)
            except Exception:
                pass
        return None

    async def _fetch_price(self) -> Optional[float]:
        hub_price = self._try_any_streaming_hub()
        if hub_price:
            self._hub_available = True
            return hub_price
        self._hub_available = False

        if not self.broker_instance:
            return None
        
        try:
            loop = asyncio.get_event_loop()
            broker_lower = self.broker_name.lower()
            
            # Normalize broker name: 'alpaca_paper' -> 'alpaca'
            broker_normalized = broker_lower.replace('_paper', '').replace('_live', '')
            
            # Handle Alpaca and Alpaca Paper
            if broker_normalized == 'alpaca':
                from alpaca.data import StockHistoricalDataClient
                from alpaca.data.requests import StockLatestQuoteRequest
                
                # AlpacaBroker stores credentials in config dict
                api_key = None
                api_secret = None
                if hasattr(self.broker_instance, 'config'):
                    api_key = self.broker_instance.config.get('api_key')
                    api_secret = self.broker_instance.config.get('api_secret')
                elif hasattr(self.broker_instance, 'api_key') and hasattr(self.broker_instance, 'secret_key'):
                    api_key = self.broker_instance.api_key
                    api_secret = self.broker_instance.secret_key
                
                if api_key and api_secret:
                    client = StockHistoricalDataClient(api_key, api_secret)
                    request = StockLatestQuoteRequest(symbol_or_symbols=self.symbol)
                    quotes = await loop.run_in_executor(None, lambda: client.get_stock_latest_quote(request))
                    if self.symbol in quotes:
                        quote = quotes[self.symbol]
                        # Use midpoint of bid/ask for more accurate price
                        bid = float(quote.bid_price) if quote.bid_price else 0
                        ask = float(quote.ask_price) if quote.ask_price else 0
                        if bid > 0 and ask > 0:
                            return (bid + ask) / 2
                        elif ask > 0:
                            return ask
                        elif bid > 0:
                            return bid
            
            elif broker_lower == 'webull':
                if hasattr(self.broker_instance, 'get_quote'):
                    quote = await self.broker_instance.get_quote(self.symbol)
                    if quote and isinstance(quote, dict) and 'close' in quote:
                        return float(quote['close'])
                    elif isinstance(quote, (int, float)) and quote > 0:
                        return float(quote)
            
            elif broker_lower == 'questrade':
                if hasattr(self.broker_instance, 'get_quote'):
                    quote = await self.broker_instance.get_quote(self.symbol)
                    if quote and isinstance(quote, dict) and 'lastTradePrice' in quote:
                        return float(quote['lastTradePrice'])
            
            elif broker_normalized == 'schwab':
                if hasattr(self.broker_instance, 'get_quote'):
                    price = await self.broker_instance.get_quote(self.symbol)
                    if price and price > 0:
                        return float(price)
            
            elif broker_normalized == 'robinhood':
                if hasattr(self.broker_instance, 'get_quote'):
                    quote = await self.broker_instance.get_quote(self.symbol)
                    if isinstance(quote, (int, float)) and quote > 0:
                        return float(quote)
                    elif isinstance(quote, dict):
                        price = quote.get('last_trade_price') or quote.get('last_extended_hours_trade_price') or quote.get('price')
                        if price:
                            return float(price)
            
            elif broker_normalized in ('tastytrade', 'ibkr'):
                if hasattr(self.broker_instance, 'get_quote'):
                    result = await self.broker_instance.get_quote(self.symbol)
                    if isinstance(result, (int, float)) and result > 0:
                        return float(result)
                    elif isinstance(result, dict):
                        price = result.get('last', 0) or result.get('price', 0) or result.get('close', 0)
                        if price and float(price) > 0:
                            return float(price)

            elif broker_normalized == 'trading212':
                try:
                    from src.services.trading212_data_hub import get_trading212_data_hub
                    hub = get_trading212_data_hub()
                    hub_price = hub.get_quote_price(self.symbol)
                    if hub_price and hub_price > 0:
                        return float(hub_price)
                except Exception:
                    pass
                if hasattr(self.broker_instance, 'get_quote'):
                    result = await self.broker_instance.get_quote(self.symbol)
                    if isinstance(result, (int, float)) and result > 0:
                        return float(result)
                finnhub_price = await self._fetch_finnhub_price()
                if finnhub_price and finnhub_price > 0:
                    return float(finnhub_price)

        except Exception as e:
            sys.stderr.write(f"[{self.broker_name.upper()}] Quote error for {self.symbol}: {e}\n")
            sys.stderr.flush()
        
        return None


class BaseConditionalOrderService(ABC):
    """
    Abstract base class for market-specific conditional order services.
    
    Each market (US, India, Canada) implements its own service with:
    - Isolated event loop and thread
    - Market-specific broker registry
    - Market-specific rate limiters
    - Market-specific price monitor fallback chain
    """
    
    MARKET = 'BASE'
    
    def __init__(self):
        self.is_running = False
        self.monitors: Dict[int, PriceMonitor] = {}
        self.monitor_tasks: Dict[int, asyncio.Task] = {}
        self.pending_orders: Dict[int, Dict] = {}
        self.broker_instances: Dict[str, Any] = {}
        self.rate_limiters: Dict[str, RateLimitTracker] = {}
        self.execution_callback: Optional[Callable] = None
        self.main_event_loop: Optional[asyncio.AbstractEventLoop] = None
        self.notification_callback: Optional[Callable] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._thread_logs = deque(maxlen=100)
        self.finnhub_api_key = os.getenv('FINNHUB_API_KEY', '')
        self.data_hubs: Dict[str, Any] = {}
        # Breakout-reset guard: if the price is already past the trigger when an
        # order is created, wait for it to pull back to the other side first
        # before allowing the order to fire. Prevents immediate execution.
        self._price_reset_needed: Dict[int, bool] = {}
        
        self._init_rate_limiters()
    
    def set_data_hub(self, broker_key: str, hub: Any):
        """Register a streaming data hub for a broker (e.g., 'webull', 'schwab')."""
        self.data_hubs[broker_key.lower()] = hub
        sys.stderr.write(f"[{self.MARKET}] Registered data hub for {broker_key}\n")
        sys.stderr.flush()
        
        if self._loop:
            asyncio.run_coroutine_threadsafe(
                self._upgrade_to_streaming(broker_key, hub),
                self._loop
            )
            # Also wait for hub to become streaming (handles Schwab which connects after hub registration)
            asyncio.run_coroutine_threadsafe(
                self._upgrade_when_streaming(broker_key, hub),
                self._loop
            )

    async def _upgrade_when_streaming(self, broker_key: str, hub: Any, timeout: float = 60.0):
        """Wait until hub reports is_streaming(), then re-run monitor upgrade (fixes Schwab late-connect)."""
        if not hasattr(hub, 'is_streaming'):
            return
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(1)
            if hub.is_streaming():
                sys.stderr.write(f"[{self.MARKET}] Hub for {broker_key} now streaming — upgrading any REST monitors\n")
                sys.stderr.flush()
                await self._upgrade_to_streaming(broker_key, hub)
                broker_lower = broker_key.lower()
                for order_id, monitor in list(self.monitors.items()):
                    if isinstance(monitor, StreamingPriceMonitor) and not monitor._using_rest_fallback:
                        order = self.pending_orders.get(order_id)
                        if order:
                            order_broker_key = order.get('broker_primary', '').lower().replace('_paper', '').replace('_live', '')
                            if order_broker_key == broker_lower:
                                new_ds = f"{broker_lower}_stream"
                                from gui_app.database import update_conditional_order_status
                                update_conditional_order_status(order_id, 'ACTIVE_MONITORING', data_source_active=new_ds)
                                self._log(f"#{order_id} data source upgraded to {new_ds}")
                return
    
    async def _upgrade_to_streaming(self, broker_key: str, hub: Any):
        """Upgrade Finnhub/REST monitors to streaming when a hub becomes available."""
        broker_lower = broker_key.lower()
        upgraded_count = 0
        
        fallback_monitors = [oid for oid, mon in self.monitors.items()
                              if isinstance(mon, (FinnhubPriceMonitor, YFinancePriceMonitor, BrokerPriceMonitor))]
        if not fallback_monitors:
            return
        
        self._log(f"Checking {len(fallback_monitors)} monitor(s) for streaming upgrade via {broker_key}")
        
        for order_id in fallback_monitors:
            monitor = self.monitors.get(order_id)
            if not monitor:
                continue
            
            if isinstance(monitor, StreamingPriceMonitor):
                continue
            
            order = self.pending_orders.get(order_id)
            if not order:
                continue
            
            order_broker = order.get('broker_primary', '').lower()
            order_broker_key = order_broker.replace('_paper', '').replace('_live', '')
            
            if order_broker_key == broker_lower or order_broker == broker_lower:
                current_monitor = self.monitors.get(order_id)
                if current_monitor is not monitor or isinstance(current_monitor, StreamingPriceMonitor):
                    continue
                
                broker_instance = self.broker_instances.get(order_broker) or self.broker_instances.get(order_broker_key)
                
                self._log(f"Upgrading #{order_id} {monitor.symbol} from {type(monitor).__name__} to streaming via {broker_key}")
                
                await monitor.stop()
                if order_id in self.monitor_tasks:
                    self.monitor_tasks[order_id].cancel()
                    try:
                        await self.monitor_tasks[order_id]
                    except asyncio.CancelledError:
                        pass
                
                if isinstance(self.monitors.get(order_id), StreamingPriceMonitor):
                    self._log(f"#{order_id} already upgraded to streaming by another path, skipping")
                    continue
                
                new_monitor = await self.build_price_monitor(order, broker_instance, order_broker)
                if new_monitor:
                    self.monitors[order_id] = new_monitor
                    task = asyncio.create_task(new_monitor.start())
                    self.monitor_tasks[order_id] = task
                    upgraded_count += 1
        
        if upgraded_count > 0:
            self._log(f"Upgraded {upgraded_count} monitor(s) to streaming via {broker_key}")
    
    def get_data_hub(self, broker_name: str) -> Optional[Any]:
        """Get the data hub for a broker (streaming or not).
        
        Returns the hub even when not actively streaming, so that
        StreamingPriceMonitor can attempt to subscribe and use its
        internal REST fallback chain (broker REST → Finnhub).
        """
        broker_lower = broker_name.lower().replace('_paper', '').replace('_live', '')
        hub = self.data_hubs.get(broker_lower)
        return hub if hub else None
    
    def is_hub_streaming(self, broker_name: str) -> bool:
        """Check if a broker's data hub is actively streaming."""
        broker_lower = broker_name.lower().replace('_paper', '').replace('_live', '')
        hub = self.data_hubs.get(broker_lower)
        return bool(hub and hasattr(hub, 'is_streaming') and hub.is_streaming())
    
    @abstractmethod
    def _init_rate_limiters(self):
        """Initialize market-specific rate limiters."""
        pass
    
    @abstractmethod
    def get_supported_brokers(self) -> List[str]:
        """Return list of broker names supported by this market."""
        pass
    
    @abstractmethod
    async def build_price_monitor(self, order: Dict, broker_instance: Any, broker_name: str) -> Optional[PriceMonitor]:
        """Build a price monitor for the given order using market-specific logic."""
        pass
    
    def _log(self, msg: str):
        timestamp = datetime.now().strftime('%H:%M:%S')
        full_msg = f"[{timestamp}] [{self.MARKET}] {msg}"
        self._thread_logs.append(full_msg)
        sys.stderr.write(f"[{self.MARKET}] {msg}\n")
        sys.stderr.flush()
    
    def _calculate_expiry(self, expiry_setting: str) -> Optional[str]:
        """Calculate expiry datetime based on legacy setting (end_of_day, 1_hour, 4_hours, 1_day).
        
        All times are stored in UTC for consistency.
        """
        if not expiry_setting:
            return None
        
        now_utc = datetime.utcnow()
        
        if expiry_setting == 'end_of_day':
            # Set expiry to 4 PM EST market close, stored as UTC (21:00 UTC or 20:00 UTC during DST)
            try:
                from zoneinfo import ZoneInfo
                est = ZoneInfo('America/New_York')
                utc = ZoneInfo('UTC')
                now_est = datetime.now(est)
                expiry_est = now_est.replace(hour=16, minute=0, second=0, microsecond=0)
                if expiry_est <= now_est:
                    # Already past 4 PM EST - set to next trading day
                    expiry_est = expiry_est + timedelta(days=1)
                # Convert to UTC for storage
                expiry_utc = expiry_est.astimezone(utc)
                expiry = expiry_utc.replace(tzinfo=None)
            except ImportError:
                # Fallback: 4 PM EST = 21:00 UTC (or 20:00 during DST)
                # Using 21:00 UTC as conservative estimate
                expiry = now_utc.replace(hour=21, minute=0, second=0, microsecond=0)
                if expiry <= now_utc:
                    expiry = expiry + timedelta(days=1)
        elif expiry_setting == '1_hour':
            expiry = now_utc + timedelta(hours=1)
        elif expiry_setting == '4_hours':
            expiry = now_utc + timedelta(hours=4)
        elif expiry_setting == '1_day':
            expiry = now_utc + timedelta(days=1)
        else:
            # Unknown setting - no expiry
            return None
        
        return expiry.strftime('%Y-%m-%d %H:%M:%S')
    
    def set_broker_instance(self, broker_name: str, instance: Any):
        """Register a broker instance for this market's price monitoring."""
        broker_lower = broker_name.lower()
        if broker_lower in [b.lower() for b in self.get_supported_brokers()]:
            self.broker_instances[broker_lower] = instance
            self._log(f"Registered broker: {broker_name}")
            
            # Upgrade any monitors using fallback data sources to use this broker
            if self._loop:
                asyncio.run_coroutine_threadsafe(
                    self._upgrade_fallback_monitors(broker_name, instance),
                    self._loop
                )
        else:
            self._log(f"Broker {broker_name} not supported for {self.MARKET} market")
    
    async def _upgrade_fallback_monitors(self, broker_name: str, broker_instance: Any):
        """Upgrade monitors using fallback data sources to use the newly registered broker."""
        broker_lower = broker_name.lower()
        upgraded_count = 0
        
        fallback_monitors = [oid for oid, mon in self.monitors.items() 
                              if isinstance(mon, (FinnhubPriceMonitor, YFinancePriceMonitor))]
        if not fallback_monitors:
            return
        
        self._log(f"Checking {len(fallback_monitors)} fallback monitor(s) for upgrade to {broker_name}")
        
        for order_id, monitor in list(self.monitors.items()):
            # Check if this monitor is using a fallback (Finnhub/yfinance) and should use this broker
            if isinstance(monitor, (FinnhubPriceMonitor, YFinancePriceMonitor)):
                # Check if this order is configured for this broker
                order = self.pending_orders.get(order_id)
                if not order:
                    continue
                
                order_broker = order.get('broker_primary', '').lower()
                order_broker_key = order_broker.replace('_paper', '').replace('_live', '')
                broker_key = broker_lower.replace('_paper', '').replace('_live', '')
                
                if order_broker_key == broker_key or order_broker == broker_lower:
                    current = self.monitors.get(order_id)
                    if current is not monitor or isinstance(current, StreamingPriceMonitor):
                        continue
                    
                    self._log(f"Upgrading #{order_id} {monitor.symbol} from fallback to {broker_name}")
                    
                    await monitor.stop()
                    if order_id in self.monitor_tasks:
                        self.monitor_tasks[order_id].cancel()
                        try:
                            await self.monitor_tasks[order_id]
                        except asyncio.CancelledError:
                            pass
                    
                    if isinstance(self.monitors.get(order_id), StreamingPriceMonitor):
                        self._log(f"#{order_id} already upgraded to streaming, skipping")
                        continue
                    
                    new_monitor = await self.build_price_monitor(order, broker_instance, broker_name)
                    if new_monitor:
                        self.monitors[order_id] = new_monitor
                        task = asyncio.create_task(new_monitor.start())
                        self.monitor_tasks[order_id] = task
                        upgraded_count += 1
        
        if upgraded_count > 0:
            self._log(f"Upgraded {upgraded_count} monitor(s) to {broker_name}")
    
    def set_execution_callback(self, callback: Callable, main_loop: Optional[asyncio.AbstractEventLoop] = None):
        self.execution_callback = callback
        self.main_event_loop = main_loop
    
    def set_notification_callback(self, callback: Callable):
        self.notification_callback = callback
    
    def is_enabled(self) -> bool:
        settings = get_conditional_order_settings()
        return settings.get('enabled', False)
    
    def start(self):
        """Start the service in its own thread with isolated event loop."""
        if self.is_running:
            self._log("Already running")
            return
        
        self._log("Starting service...")
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True, name=f"Conditional-{self.MARKET}")
        self._thread.start()
    
    def _run_event_loop(self):
        """Run event loop in dedicated thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self.is_running = True
        self._log("Event loop started")
        
        try:
            self._loop.run_until_complete(self._main_loop())
        except Exception as e:
            self._log(f"Event loop error: {e}")
        finally:
            self._loop.close()
            self.is_running = False
            self._log("Event loop stopped")
    
    async def _main_loop(self):
        """Main monitoring loop."""
        await self._restore_active_orders()
        
        while self.is_running:
            try:
                await self._check_expirations()
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._log(f"Main loop error: {e}")
                await asyncio.sleep(5)
    
    async def _restore_active_orders(self):
        """Restore monitors for active orders on startup."""
        orders = get_active_conditional_orders()
        market_orders = [o for o in orders if o.get('market', 'US') == self.MARKET]
        
        if not market_orders:
            self._log("No active orders to restore")
            return
        
        needed_brokers = set()
        for order in market_orders:
            bp = order.get('broker_primary', '').lower().replace('_paper', '').replace('_live', '')
            if bp:
                needed_brokers.add(bp)
        
        if needed_brokers:
            wait_deadline = asyncio.get_event_loop().time() + 10.0
            while asyncio.get_event_loop().time() < wait_deadline:
                registered = set(self.broker_instances.keys())
                missing = needed_brokers - registered
                has_any_hub = bool(self.data_hubs)
                if not missing and has_any_hub:
                    self._log(f"All needed brokers registered: {needed_brokers}, hubs: {list(self.data_hubs.keys())}")
                    break
                if not missing and (asyncio.get_event_loop().time() - (wait_deadline - 10.0)) > 3.0:
                    self._log(f"Brokers ready, no data hubs after 3s — proceeding with broker REST")
                    break
                await asyncio.sleep(0.25)
            else:
                missing = needed_brokers - set(self.broker_instances.keys())
                if missing:
                    self._log(f"Broker wait timeout — still missing: {missing} (will use fallback)")
        
        executing_orders = [o for o in market_orders if o.get('status') == 'EXECUTING']
        monitoring_orders = [o for o in market_orders if o.get('status') != 'EXECUTING']
        
        if executing_orders:
            self._log(f"Found {len(executing_orders)} orders stuck in EXECUTING — re-executing")
            for order in executing_orders:
                order_id = order['id']
                symbol = order.get('symbol', '?')
                broker = order.get('broker_primary', '?')
                self._log(f"Re-executing stuck order #{order_id} {symbol} on {broker}")
                try:
                    self.pending_orders[order_id] = order
                    self._price_reset_needed[order_id] = False
                    update_conditional_order_status(order_id, 'ACTIVE_MONITORING')
                    await self._execute_order(order_id, order)
                except Exception as e:
                    self._log(f"Re-execution failed for #{order_id}: {e}")
                    update_conditional_order_status(
                        order_id, 'ERROR',
                        event='RESTART_REEXEC_FAILED',
                        error_message=f"Re-execution on restart failed: {e}"
                    )
        
        self._log(f"Restoring {len(monitoring_orders)} active orders")
        for order in monitoring_orders:
            order_id = order['id']
            self.pending_orders[order_id] = order
            self._price_reset_needed[order_id] = False
            await self._start_monitor(order_id, order)
        
        self._log(f"Restored {len(monitoring_orders)} orders")
    
    async def _check_expirations(self):
        """Check and expire old orders."""
        expired_count = expire_old_conditional_orders()
        if expired_count > 0:
            self._log(f"Expired {expired_count} old orders")
            for order_id in list(self.pending_orders.keys()):
                order = get_conditional_order_by_id(order_id)
                if order and order.get('status') == 'EXPIRED':
                    try:
                        notify_conditional_expired(
                            symbol=order.get('symbol', 'UNKNOWN'),
                            trigger_price=order.get('trigger_price', 0),
                            broker=order.get('broker_primary', ''),
                            order_id=order_id,
                            reason="Time expired"
                        )
                    except Exception as e:
                        self._log(f"Notification error (expired): {e}")
                    await self._cleanup_order(order_id)
    
    def create_order(self, channel_id: str, parsed_signal: Dict[str, Any], broker: str) -> Optional[int]:
        """Create a new conditional order."""
        if not self.is_enabled():
            self._log("Service disabled")
            return None
        
        channel_settings = get_channel_conditional_settings(channel_id)
        self._log(f"Channel settings for {channel_id}: "
                  f"timeout={channel_settings.get('order_timeout_minutes') or channel_settings.get('conditional_order_timeout_minutes') or channel_settings.get('conditional_order_expiry')}, "
                  f"position_size_pct={channel_settings.get('position_size_pct')}, "
                  f"default_qty={channel_settings.get('default_quantity')}, "
                  f"exit_mode={channel_settings.get('exit_strategy_mode')}, "
                  f"slippage={channel_settings.get('slippage_protection_enabled')}/{channel_settings.get('slippage_max_pct')}, "
                  f"trailing={channel_settings.get('trailing_stop_pct')}")
        is_entry_confirmation = bool(parsed_signal.get('_entry_confirmation'))
        if not channel_settings.get('conditional_order_enabled', True) and not is_entry_confirmation:
            self._log(f"Disabled for channel {channel_id}")
            return None
        
        # Priority: passed broker (from enabled_brokers) > legacy broker_override setting
        effective_broker = broker or channel_settings.get('broker_override')
        if not effective_broker:
            self._log(f"No broker for channel {channel_id}")
            return None
        self._log(f"Using broker: {effective_broker} for channel {channel_id}")
        
        trigger_price = parsed_signal.get('trigger_price', 0)
        trigger_type = parsed_signal.get('trigger_type', 'over')
        
        # ADJUST OFFSET: Apply channel-level trigger offset if configured
        # Falls back to global conditional order settings if channel has no offset
        from gui_app.database import compute_adjusted_trigger
        
        offset_mode = channel_settings.get('trigger_offset_mode', 'percent') or 'percent'
        if offset_mode == 'dollar':
            offset_value = channel_settings.get('trigger_offset_value', 0.0) or 0.0
        else:
            offset_value = channel_settings.get('trigger_offset_percent', 0.0) or 0.0
        
        if offset_value == 0:
            try:
                from gui_app.database import get_connection
                _g_conn = get_connection()
                _g_cursor = _g_conn.cursor()
                _g_cursor.execute("SELECT key, value FROM settings WHERE key LIKE 'conditional_order_trigger_offset_%'")
                global_offset_settings = {r['key']: r['value'] for r in _g_cursor.fetchall()}
                global_mode = global_offset_settings.get('conditional_order_trigger_offset_mode', 'percent') or 'percent'
                if global_mode == 'dollar':
                    global_val = global_offset_settings.get('conditional_order_trigger_offset_value', '0')
                else:
                    global_val = global_offset_settings.get('conditional_order_trigger_offset_percent', '0')
                try:
                    global_val_float = float(global_val)
                except (ValueError, TypeError):
                    global_val_float = 0.0
                if global_val_float != 0:
                    offset_mode = global_mode
                    offset_value = global_val_float
                    print(f"[CONDITIONAL] Channel {channel_id} trigger offset: {offset_value} ({offset_mode}) [from global settings]", flush=True)
                else:
                    print(f"[CONDITIONAL] Channel {channel_id} trigger offset: {offset_value} ({offset_mode})", flush=True)
            except Exception as _g_err:
                print(f"[CONDITIONAL] Channel {channel_id} trigger offset: {offset_value} ({offset_mode}) [global fallback error: {_g_err}]", flush=True)
        else:
            print(f"[CONDITIONAL] Channel {channel_id} trigger offset: {offset_value} ({offset_mode})", flush=True)
        
        if offset_value != 0:
            adjusted_price = compute_adjusted_trigger(trigger_price, trigger_type, offset_mode, offset_value)
            if offset_mode == 'dollar':
                print(f"[CONDITIONAL] ✓ Applied {'+'if trigger_type=='over' else '-'}${abs(offset_value):.2f} offset: ${trigger_price} -> ${adjusted_price:.4f}", flush=True)
            else:
                sign = '+' if trigger_type == 'over' else '-'
                print(f"[CONDITIONAL] ✓ Applied {sign}{offset_value}% offset: ${trigger_price} -> ${adjusted_price:.4f}", flush=True)
        else:
            adjusted_price = trigger_price
            print(f"[CONDITIONAL] No offset configured, using signal price: ${trigger_price}", flush=True)
        
        timeout_minutes = channel_settings.get('order_timeout_minutes') or channel_settings.get('conditional_order_timeout_minutes')
        if timeout_minutes:
            # Use UTC for consistent timezone handling
            expires_at = (datetime.utcnow() + timedelta(minutes=timeout_minutes)).strftime('%Y-%m-%d %H:%M:%S')
            self._log(f"Using channel timeout: {timeout_minutes} minutes")
        else:
            # Fall back to legacy expiry setting (end_of_day, 1_hour, 4_hours, 1_day)
            expiry_setting = channel_settings.get('conditional_order_expiry')
            expires_at = self._calculate_expiry(expiry_setting)
            if expires_at:
                self._log(f"Using legacy expiry setting: {expiry_setting}")
            else:
                self._log(f"No timeout configured - order has no expiry")
        
        size_mode = parsed_signal.get('size_mode')
        qty_value = None
        
        if size_mode == 'percent_account':
            qty_value = parsed_signal.get('position_size_pct')
        elif size_mode == 'fixed_qty':
            qty_value = parsed_signal.get('fixed_qty')
        else:
            if channel_settings.get('position_size_pct'):
                size_mode = 'percent_account'
                qty_value = channel_settings.get('position_size_pct')
            elif channel_settings.get('default_quantity'):
                size_mode = 'fixed_qty'
                qty_value = channel_settings.get('default_quantity')
        
        profit_targets = parsed_signal.get('profit_targets', [])
        if not profit_targets:
            channel_targets = []
            for i in range(1, 5):
                pt_pct = channel_settings.get(f'profit_target_{i}_pct')
                if pt_pct and pt_pct > 0:
                    channel_targets.append(pt_pct)
            if channel_targets:
                profit_targets = channel_targets
        
        stop_loss_value = parsed_signal.get('stop_loss_value') or parsed_signal.get('stop_loss')
        stop_loss_type = parsed_signal.get('stop_loss_type')
        stop_loss_fixed = parsed_signal.get('stop_loss_fixed')
        stop_loss_pct = parsed_signal.get('stop_loss_pct')
        
        if not stop_loss_value and channel_settings.get('stop_loss_pct'):
            stop_loss_type = 'percent'
            stop_loss_value = channel_settings.get('stop_loss_pct')
            stop_loss_pct = stop_loss_value
        
        target_ranges = parsed_signal.get('target_ranges')
        target_ranges_json = json.dumps(target_ranges) if target_ranges else None
        
        # Get channel-level settings for exit strategy, slippage, and trailing stop
        exit_strategy_mode = channel_settings.get('exit_strategy_mode', 'signal')
        slippage_protection_enabled = 1 if channel_settings.get('slippage_protection_enabled') else 0
        slippage_max_pct = channel_settings.get('slippage_max_pct')
        
        # Breakout Reset Guard - require pullback before triggering if price already past trigger
        breakout_reset_enabled = 1 if channel_settings.get('breakout_reset_enabled', 1) else 0
        
        # Limit Cap - price ceiling for limit orders to prevent chasing
        limit_cap_enabled = 1 if channel_settings.get('limit_cap_enabled') else 0
        limit_cap_pct = channel_settings.get('limit_cap_pct') or 5.0
        
        # Compute limit_price at order creation (will be used at trigger execution)
        # For BUY orders: limit_price = trigger + cap% (ceiling)
        # For SELL orders: limit_price = trigger - cap% (floor)
        limit_price = None
        if limit_cap_enabled and limit_cap_pct and limit_cap_pct != 0 and adjusted_price:
            if trigger_type in ('over', 'ABOVE', 'PRICE_ABOVE', 'BTO'):
                # Buy: max price = trigger + cap%
                limit_price = round(adjusted_price * (1 + limit_cap_pct / 100), 4)
                self._log(f"Limit cap computed: trigger=${adjusted_price} + {limit_cap_pct}% = limit=${limit_price} (BUY ceiling)")
            else:
                # Sell: min price = trigger - cap%
                limit_price = round(adjusted_price * (1 - limit_cap_pct / 100), 4)
                self._log(f"Limit cap computed: trigger=${adjusted_price} - {limit_cap_pct}% = limit=${limit_price} (SELL floor)")
        
        # Trailing stop - signal overrides channel settings
        trailing_stop_pct = parsed_signal.get('trailing_stop_pct') or channel_settings.get('trailing_stop_pct')
        trailing_activation_pct = parsed_signal.get('trailing_activation_pct') or channel_settings.get('trailing_activation_pct')
        trailing_stop_enabled = 1 if trailing_stop_pct and trailing_stop_pct > 0 else 0
        
        # Build settings source metadata for audit trail
        settings_sources = []
        if timeout_minutes:
            settings_sources.append(f"timeout:channel({timeout_minutes}min)")
        elif expires_at:
            settings_sources.append(f"timeout:channel({channel_settings.get('conditional_order_expiry', 'default')})")
        if size_mode == 'percent_account' and not parsed_signal.get('size_mode'):
            settings_sources.append(f"sizing:channel({qty_value}%)")
        elif size_mode == 'fixed_qty' and not parsed_signal.get('size_mode'):
            settings_sources.append(f"sizing:channel({qty_value}qty)")
        if slippage_protection_enabled:
            settings_sources.append(f"slippage:channel({slippage_max_pct}%)")
        if limit_cap_enabled:
            settings_sources.append(f"limit_cap:channel({limit_cap_pct}%)")
        if not breakout_reset_enabled:
            settings_sources.append("breakout_reset:disabled")
        if trailing_stop_pct and not parsed_signal.get('trailing_stop_pct'):
            settings_sources.append(f"trailing:channel({trailing_stop_pct}%)")
        if exit_strategy_mode != 'signal':
            settings_sources.append(f"exit_mode:channel({exit_strategy_mode})")
        settings_source = '; '.join(settings_sources) if settings_sources else None
        
        self._log(f"Channel settings applied: exit_mode={exit_strategy_mode}, slippage={slippage_protection_enabled}/{slippage_max_pct}, "
                  f"limit_cap={limit_cap_enabled}/{limit_cap_pct}%, trailing={trailing_stop_pct}/{trailing_activation_pct}")
        
        order_id = create_conditional_order(
            channel_id=channel_id,
            symbol=parsed_signal.get('symbol'),
            trigger_type=trigger_type,
            trigger_price=adjusted_price,
            adjusted_trigger_price=adjusted_price,
            broker_primary=effective_broker,
            stop_loss_type=stop_loss_type,
            stop_loss_value=stop_loss_value,
            stop_loss_fixed=stop_loss_fixed,
            stop_loss_pct=stop_loss_pct,
            take_profit_targets=json.dumps(profit_targets) if profit_targets else None,
            target_ranges=target_ranges_json,
            size_mode=size_mode,
            qty_value=qty_value,
            calculated_qty=parsed_signal.get('qty') or parsed_signal.get('quantity'),
            expires_at=expires_at,
            original_message=parsed_signal.get('original_message'),
            asset_type='option' if parsed_signal.get('strike') else 'stock',
            strike=parsed_signal.get('strike'),
            opt_type=parsed_signal.get('opt_type'),
            market=self.MARKET,
            expiry=parsed_signal.get('expiry'),
            lot_size=parsed_signal.get('lot_size'),
            lots=parsed_signal.get('lots'),
            exit_strategy_mode=exit_strategy_mode,
            slippage_protection_enabled=slippage_protection_enabled,
            slippage_max_pct=slippage_max_pct,
            trailing_stop_enabled=trailing_stop_enabled,
            trailing_stop_pct=trailing_stop_pct,
            trailing_activation_pct=trailing_activation_pct,
            settings_source=settings_source,
            author_name=parsed_signal.get('author_name'),
            limit_cap_enabled=limit_cap_enabled,
            limit_cap_pct=limit_cap_pct,
            limit_price=limit_price,
            message_id=parsed_signal.get('message_id'),
            breakout_reset_enabled=breakout_reset_enabled,
            original_signal_price=parsed_signal.get('trigger_price', 0),
        )
        
        if order_id:
            self._log(f"Created order #{order_id} for {parsed_signal.get('symbol')}")
            self._schedule_monitoring(order_id)
            
            try:
                notify_conditional_created(
                    symbol=parsed_signal.get('symbol', 'UNKNOWN'),
                    trigger_type=trigger_type,
                    trigger_price=adjusted_price,
                    broker=effective_broker,
                    order_id=order_id,
                    stop_loss=stop_loss_value,
                    expires_at=expires_at,
                    channel_id=channel_id
                )
            except Exception as e:
                self._log(f"Notification error (created): {e}")
            
            # Register signal context for follow-up message correlation
            try:
                from src.services.signal_conversation_state import get_conversation_state_manager
                manager = get_conversation_state_manager()
                author_id = parsed_signal.get('author_id') or parsed_signal.get('_author_id')
                if channel_id and author_id:
                    manager.register_signal_context(
                        channel_id=int(channel_id),
                        author_id=int(author_id),
                        symbol=parsed_signal.get('symbol'),
                        order_id=order_id
                    )
                    self._log(f"Registered context for follow-up tracking: channel={channel_id}, author={author_id}")
            except Exception as e:
                self._log(f"Could not register signal context: {e}")
        
        return order_id
    
    def _schedule_monitoring(self, order_id: int):
        """Schedule price monitoring for an order."""
        order = get_conditional_order_by_id(order_id)
        if not order:
            return
        
        update_conditional_order_status(
            order_id,
            'ACTIVE_MONITORING',
            event='MONITORING_STARTED',
            details=f"Started monitoring {order['symbol']}"
        )
        
        self.pending_orders[order_id] = order
        self._price_reset_needed[order_id] = bool(order.get('breakout_reset_enabled', 1))
        
        if self.is_running and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._start_monitor(order_id, order),
                self._loop
            )
    
    async def _start_monitor(self, order_id: int, order: Dict):
        """Start a price monitor for an order using market-specific logic."""
        symbol = order['symbol']
        broker = order['broker_primary']
        
        self._log(f"Starting monitor for #{order_id} {symbol} broker={broker}")
        
        # Normalize broker name for lookup: 'alpaca_paper' -> 'alpaca', 'ALPACA_PAPER' -> 'alpaca'
        broker_lower = broker.lower() if broker else ''
        broker_key = broker_lower.replace('_paper', '').replace('_live', '')
        broker_instance = self.broker_instances.get(broker_key) if broker_key else None
        
        if not broker_instance and broker_lower:
            # Fallback: try direct lookup
            broker_instance = self.broker_instances.get(broker_lower)
        
        monitor = await self.build_price_monitor(order, broker_instance, broker or '')
        
        if not monitor:
            self._log(f"No price monitor available for #{order_id}")
            update_conditional_order_status(
                order_id,
                'ERROR',
                event='NO_PRICE_SOURCE',
                error_message='No price source available for this market'
            )
            try:
                notify_conditional_failed(
                    symbol=symbol,
                    broker=broker or '',
                    order_id=order_id,
                    error="No price source available",
                    stage="monitoring"
                )
            except Exception as e:
                self._log(f"Notification error (no price source): {e}")
            return
        
        self.monitors[order_id] = monitor
        
        def _on_monitor_done(task: asyncio.Task, oid: int = order_id):
            try:
                result = task.result()
                if result is False:
                    self._log(f"Order #{oid}: Monitor returned False")
                    if oid in self.monitors:
                        del self.monitors[oid]
                    if oid in self.pending_orders:
                        del self.pending_orders[oid]
                    if oid in self.monitor_tasks:
                        del self.monitor_tasks[oid]
                    self._price_reset_needed.pop(oid, None)
            except asyncio.CancelledError:
                self._log(f"Monitor #{oid} cancelled")
            except Exception as e:
                self._log(f"Monitor error #{oid}: {e}")
        
        async def price_callback(sym: str, price: float):
            await self._on_price_update(order_id, sym, price)
        
        monitor.callback = price_callback
        
        task = asyncio.create_task(monitor.start())
        task.add_done_callback(lambda t: _on_monitor_done(t, order_id))
        self.monitor_tasks[order_id] = task
        
        self._log(f"Started monitor task for #{order_id}")
    
    async def _cleanup_order(self, order_id: int):
        """Remove an order from all in-memory tracking structures."""
        order = self.pending_orders.get(order_id)
        if order_id in self.monitors:
            await self.monitors[order_id].stop()
            del self.monitors[order_id]
        if order_id in self.monitor_tasks:
            self.monitor_tasks[order_id].cancel()
            del self.monitor_tasks[order_id]
        if order and order.get('broker', '').lower().replace('_paper', '').replace('_live', '') == 'trading212':
            try:
                from src.services.trading212_data_hub import get_trading212_data_hub
                t212_hub = get_trading212_data_hub()
                if t212_hub:
                    t212_hub.remove_conditional_symbol(order.get('symbol', ''))
            except Exception:
                pass
        if order_id in self.pending_orders:
            del self.pending_orders[order_id]
        self._price_reset_needed.pop(order_id, None)
        if hasattr(self, '_price_log_counters'):
            self._price_log_counters.pop(order_id, None)
    
    async def _on_price_update(self, order_id: int, symbol: str, price: float):
        """Handle price update from monitor."""
        order = self.pending_orders.get(order_id)
        if not order:
            return
        
        expires_at = order.get('expires_at')
        if not expires_at:
            created_at = order.get('created_at')
            channel_id = order.get('channel_id')
            if created_at and channel_id:
                try:
                    ch_settings = get_channel_conditional_settings(str(channel_id))
                    tm = ch_settings.get('order_timeout_minutes') or ch_settings.get('conditional_order_timeout_minutes')
                    if tm:
                        created_dt = datetime.strptime(created_at.replace('T', ' ').split('.')[0], '%Y-%m-%d %H:%M:%S')
                        computed_expires = (created_dt + timedelta(minutes=tm)).strftime('%Y-%m-%d %H:%M:%S')
                        order['expires_at'] = computed_expires
                        expires_at = computed_expires
                        self._log(f"#{order_id} {symbol}: Computed missing expires_at from created_at + {tm}m → {computed_expires} UTC")
                except Exception as e:
                    self._log(f"#{order_id} expires_at fallback error: {e}")
        
        if expires_at:
            try:
                expiry_dt = datetime.strptime(expires_at, '%Y-%m-%d %H:%M:%S')
                if datetime.utcnow() >= expiry_dt:
                    self._log(f"⏰ #{order_id} {symbol} EXPIRED during price update — skipping trigger")
                    update_conditional_order_status(
                        order_id, 'EXPIRED',
                        event='EXPIRED_AT_TRIGGER',
                        details=f'Order expired at trigger check (expires_at={expires_at})'
                    )
                    await self._cleanup_order(order_id)
                    try:
                        notify_conditional_expired(
                            symbol=symbol,
                            trigger_price=order.get('trigger_price', 0),
                            broker=order.get('broker_primary', ''),
                            order_id=order_id,
                            reason=f"Timeout reached ({expires_at} UTC)"
                        )
                    except Exception:
                        pass
                    return
            except (ValueError, TypeError):
                pass
        
        # Use adjusted_trigger_price if offset has been applied, otherwise use original trigger_price
        original_trigger = order.get('trigger_price', 0)
        adjusted_trigger = order.get('adjusted_trigger_price') or original_trigger
        trigger_type = order.get('trigger_type', 'over')
        
        try:
            from gui_app.database import update_conditional_order_price
            update_conditional_order_price(order_id, price)
        except Exception:
            pass
        
        if not hasattr(self, '_price_log_counters'):
            self._price_log_counters = {}
        counter = self._price_log_counters.get(order_id, 0) + 1
        self._price_log_counters[order_id] = counter
        last = order.get('_last_logged_price')
        if last != price or counter <= 3 or counter % 10 == 0:
            order['_last_logged_price'] = price
            self._log(f"Price update #{order_id} {symbol} @ {price:.2f} (trigger: {trigger_type} {adjusted_trigger})")
        
        # ── Breakout-reset guard ──────────────────────────────────────────────────
        # If the price was already past the trigger when the order was created,
        # require it to pull back to the opposite side before we allow firing.
        if self._price_reset_needed.get(order_id, False):
            already_past = (
                (trigger_type == 'over'  and price >= adjusted_trigger) or
                (trigger_type == 'under' and price <= adjusted_trigger)
            )
            if already_past:
                created_at = order.get('created_at', '')
                grace_expired = True
                if created_at:
                    try:
                        if isinstance(created_at, str):
                            ct = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S')
                        else:
                            ct = created_at
                        age_seconds = (datetime.utcnow() - ct).total_seconds()
                        if age_seconds < 10:
                            grace_expired = False
                            self._price_reset_needed[order_id] = False
                            self._log(
                                f"#{order_id} breakout reset SKIPPED — order only {age_seconds:.1f}s old, "
                                f"price {price:.4f} already past trigger {adjusted_trigger}. "
                                f"Allowing immediate trigger (multi-broker grace)."
                            )
                    except Exception:
                        pass
                if grace_expired:
                    self._log(
                        f"#{order_id} reset pending — {price:.4f} already "
                        f"{'above' if trigger_type == 'over' else 'below'} "
                        f"trigger {adjusted_trigger}. Waiting for pullback."
                    )
                    return
            else:
                self._price_reset_needed[order_id] = False
                self._log(
                    f"#{order_id} reset complete — {price:.4f} now "
                    f"{'below' if trigger_type == 'over' else 'above'} "
                    f"trigger {adjusted_trigger}. Watching for breakout."
                )
        # ─────────────────────────────────────────────────────────────────────────

        triggered = False
        if trigger_type == 'over' and price >= adjusted_trigger:
            triggered = True
        elif trigger_type == 'under' and price <= adjusted_trigger:
            triggered = True
        
        if triggered:
            self._log(f"TRIGGERED #{order_id} {symbol}")
            try:
                notify_conditional_triggered(
                    symbol=symbol,
                    trigger_price=adjusted_trigger,
                    current_price=price,
                    broker=order.get('broker_primary', ''),
                    order_id=order_id
                )
            except Exception as e:
                self._log(f"Notification error (triggered): {e}")
            await self._execute_order(order_id, order, price)
    
    async def _execute_order(self, order_id: int, order: Dict, trigger_price: float):
        """Execute triggered order with safety checks."""
        symbol = order.get('symbol', 'UNKNOWN')
        channel_id = order.get('channel_id')
        
        # SAFETY CHECK 0: Final expiry guard (defense-in-depth)
        expires_at = order.get('expires_at')
        if expires_at:
            try:
                expiry_dt = datetime.strptime(expires_at, '%Y-%m-%d %H:%M:%S')
                if datetime.utcnow() >= expiry_dt:
                    self._log(f"⚠️ BLOCKED #{order_id} {symbol}: Order EXPIRED at execution stage (expires_at={expires_at} UTC)")
                    update_conditional_order_status(
                        order_id, 'EXPIRED',
                        event='EXPIRED_AT_EXECUTION',
                        details=f'Order expired at final execution check (expires_at={expires_at})'
                    )
                    await self._cleanup_order(order_id)
                    try:
                        notify_conditional_expired(
                            symbol=symbol,
                            trigger_price=order.get('trigger_price', 0),
                            broker=order.get('broker_primary', ''),
                            order_id=order_id,
                            reason=f"Expired at execution (timeout {expires_at} UTC)"
                        )
                    except Exception:
                        pass
                    return
            except (ValueError, TypeError):
                pass
        
        db_order = get_conditional_order_by_id(order_id)
        if db_order and db_order.get('status') == 'EXPIRED':
            self._log(f"⚠️ BLOCKED #{order_id} {symbol}: DB status is EXPIRED — blocking execution")
            await self._cleanup_order(order_id)
            return
        
        # SAFETY CHECK 1: Price staleness guard (30 second threshold)
        monitor = self.monitors.get(order_id)
        if monitor:
            staleness_sec = monitor.get_staleness_seconds() if hasattr(monitor, 'get_staleness_seconds') else 0
            if staleness_sec > 30:
                self._log(f"⚠️ BLOCKED #{order_id} {symbol}: Price stale ({staleness_sec}s > 30s threshold)")
                update_conditional_order_status(
                    order_id,
                    'PENDING_MONITOR',
                    event='STALENESS_BLOCK',
                    details=f"Price stale ({staleness_sec}s) - waiting for fresh data"
                )
                return  # Don't execute, wait for fresh price
        
        # SAFETY CHECK 2: Circuit breaker check
        try:
            from src.services.circuit_breaker import circuit_breaker
            if circuit_breaker.is_halted:
                self._log(f"⚠️ BLOCKED #{order_id} {symbol}: Global circuit breaker HALTED")
                update_conditional_order_status(
                    order_id,
                    'PENDING_MONITOR',
                    event='CIRCUIT_BREAKER_BLOCK',
                    details="Global trading halted by circuit breaker"
                )
                return  # Don't execute, trading is halted
            
            # Check channel-specific halt
            if channel_id:
                channel_state = circuit_breaker.get_channel_state(str(channel_id))
                if channel_state and channel_state.is_halted:
                    self._log(f"⚠️ BLOCKED #{order_id} {symbol}: Channel {channel_id} halted")
                    update_conditional_order_status(
                        order_id,
                        'PENDING_MONITOR',
                        event='CHANNEL_HALT_BLOCK',
                        details=f"Channel trading halted: {channel_state.reason}"
                    )
                    return
        except ImportError:
            pass  # Circuit breaker not available, continue with execution
        except Exception as cb_err:
            self._log(f"Circuit breaker check error: {cb_err}")

        try:
            from src.services.daily_pnl_limit_service import get_daily_pnl_service
            pnl_service = get_daily_pnl_service()
            broker_primary = order.get('broker_primary', '')
            if broker_primary:
                pnl_check = pnl_service.check_broker_locked(broker_primary)
                if pnl_check.get('locked'):
                    lock_type = pnl_check.get('lock_type', 'unknown')
                    pnl = pnl_check.get('daily_pnl', 0)
                    pnl_pct = pnl_check.get('daily_pnl_pct', 0)
                    if lock_type == 'trades':
                        tc = pnl_check.get('daily_trade_count', 0)
                        tl = pnl_check.get('daily_trade_limit', 0)
                        block_detail = f"Daily trade limit reached ({tc}/{tl})"
                    else:
                        block_detail = f"Daily P&L {lock_type} limit reached: ${pnl:+,.2f} ({pnl_pct:+.1f}%)"
                    self._log(f"⛔ BLOCKED #{order_id} {symbol}: {block_detail}")
                    update_conditional_order_status(
                        order_id,
                        'PENDING_MONITOR',
                        event='DAILY_PNL_BLOCK',
                        details=block_detail
                    )
                    return
        except ImportError:
            pass
        except Exception as dpnl_err:
            self._log(f"Daily P&L check error: {dpnl_err}")

        slippage_enabled = order.get('slippage_protection_enabled', 0)
        slippage_max_pct = order.get('slippage_max_pct', 0.0) or 0.0
        original_trigger = order.get('trigger_price', 0)
        trigger_type = order.get('trigger_type', 'over')
        
        if slippage_enabled and slippage_max_pct > 0 and original_trigger > 0:
            if trigger_type == 'over':
                max_allowed_price = original_trigger * (1 + slippage_max_pct / 100)
                if trigger_price > max_allowed_price:
                    slippage_pct = ((trigger_price - original_trigger) / original_trigger) * 100
                    self._log(f"⚠️ SLIPPAGE WARNING #{order_id} {symbol}: {slippage_pct:.1f}% > {slippage_max_pct}% — deferring to broker execution wait-and-recover")
            else:
                min_allowed_price = original_trigger * (1 - slippage_max_pct / 100)
                if trigger_price < min_allowed_price:
                    slippage_pct = ((original_trigger - trigger_price) / original_trigger) * 100
                    self._log(f"⚠️ SLIPPAGE WARNING #{order_id} {symbol}: {slippage_pct:.1f}% > {slippage_max_pct}% — deferring to broker execution wait-and-recover")
            
            self._log(f"✓ Slippage check: ${trigger_price:.2f} vs trigger ${original_trigger:.2f} (threshold {slippage_max_pct}%) — enforcement deferred to broker pipeline")
        
        cur_monitor = self.monitors.get(order_id)
        is_fallback_source = isinstance(cur_monitor, (FinnhubPriceMonitor, YFinancePriceMonitor)) if cur_monitor else False
        broker_primary = order.get('broker_primary', '')
        
        if is_fallback_source and broker_primary:
            source_name = 'Finnhub' if isinstance(cur_monitor, FinnhubPriceMonitor) else 'YFinance'
            self._log(f"⚠️ #{order_id} {symbol} triggered on {source_name} fallback — stopping monitor and waiting up to 5s for broker {broker_primary} recovery")
            
            if order_id in self.monitors:
                await self.monitors[order_id].stop()
                del self.monitors[order_id]
            if order_id in self.monitor_tasks:
                self.monitor_tasks[order_id].cancel()
                del self.monitor_tasks[order_id]
            
            broker_recovered = False
            broker_key = broker_primary.lower().replace(' ', '_')
            for _ in range(20):
                if broker_key in self.broker_instances:
                    hub = self.data_hubs.get(broker_key)
                    is_streaming = hub.is_streaming() if hub and callable(getattr(hub, 'is_streaming', None)) else False
                    if is_streaming:
                        self._log(f"✓ #{order_id} {symbol} broker {broker_primary} streaming recovered — proceeding with execution")
                        broker_recovered = True
                        break
                    else:
                        self._log(f"✓ #{order_id} {symbol} broker {broker_primary} REST available — proceeding with execution")
                        broker_recovered = True
                        break
                await asyncio.sleep(0.25)
            
            if not broker_recovered:
                reason = f"Broker {broker_primary} API/streaming unavailable after 5s wait — order cancelled for safety"
                self._log(f"❌ #{order_id} {symbol}: {reason}")
                
                if order_id in self.pending_orders:
                    del self.pending_orders[order_id]
                self._price_reset_needed.pop(order_id, None)
                
                update_conditional_order_status(
                    order_id, 'CANCELLED',
                    event='BROKER_UNAVAILABLE',
                    details=reason
                )
                try:
                    notify_conditional_failed(
                        symbol=symbol,
                        trigger_price=order.get('trigger_price', 0),
                        broker=broker_primary,
                        order_id=order_id,
                        stage='monitoring',
                        error=reason
                    )
                except Exception:
                    pass
                return
            
            if order_id in self.pending_orders:
                del self.pending_orders[order_id]
            self._price_reset_needed.pop(order_id, None)
        else:
            if order_id in self.monitors:
                await self.monitors[order_id].stop()
                del self.monitors[order_id]
            
            if order_id in self.monitor_tasks:
                self.monitor_tasks[order_id].cancel()
                del self.monitor_tasks[order_id]
            
            if order_id in self.pending_orders:
                del self.pending_orders[order_id]
            self._price_reset_needed.pop(order_id, None)
        
        update_conditional_order_status(
            order_id,
            'TRIGGERED',
            triggered_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            event='CONDITION_MET',
            details=f"Price reached {trigger_price} (staleness OK, circuit breaker OK)"
        )
        
        if self.execution_callback:
            try:
                order['triggered_price'] = trigger_price
                result = self.execution_callback(order, trigger_price)
                callback_success = True
                if asyncio.iscoroutine(result):
                    if self.main_event_loop and self.main_event_loop.is_running():
                        future = asyncio.run_coroutine_threadsafe(result, self.main_event_loop)
                        try:
                            cb_result = future.result(timeout=30)
                            if cb_result is False:
                                callback_success = False
                                self._log(f"Execution callback returned False for #{order_id}")
                        except Exception as e:
                            callback_success = False
                            self._log(f"Async execution error #{order_id}: {e}")
                            update_conditional_order_status(
                                order_id,
                                'ERROR',
                                event='EXECUTION_FAILED',
                                error_message=f"Async callback error: {str(e)[:200]}"
                            )
                    else:
                        callback_success = False
                        self._log(f"Cannot execute async callback - no main event loop")
                        update_conditional_order_status(
                            order_id,
                            'ERROR',
                            event='EXECUTION_FAILED',
                            error_message="No main event loop available"
                        )
                if callback_success:
                    update_conditional_order_status(order_id, 'EXECUTING')
            except Exception as e:
                self._log(f"Execution error #{order_id}: {e}")
                update_conditional_order_status(
                    order_id,
                    'ERROR',
                    event='EXECUTION_FAILED',
                    error_message=str(e)
                )
                try:
                    notify_conditional_failed(
                        symbol=symbol,
                        broker=order.get('broker_primary', ''),
                        order_id=order_id,
                        error=str(e),
                        stage="execution"
                    )
                except Exception as ne:
                    self._log(f"Notification error (execution failed): {ne}")
    
    def cancel_order(self, order_id: int) -> bool:
        """Cancel a conditional order."""
        order = self.pending_orders.get(order_id) or get_conditional_order_by_id(order_id)
        
        if order_id in self.monitors:
            if self._loop:
                asyncio.run_coroutine_threadsafe(
                    self.monitors[order_id].stop(),
                    self._loop
                )
            del self.monitors[order_id]
        
        if order_id in self.monitor_tasks:
            self.monitor_tasks[order_id].cancel()
            del self.monitor_tasks[order_id]
        
        if order_id in self.pending_orders:
            del self.pending_orders[order_id]
        self._price_reset_needed.pop(order_id, None)
        
        result = cancel_conditional_order(order_id)
        
        if result and order:
            try:
                notify_conditional_cancelled(
                    symbol=order.get('symbol', 'UNKNOWN'),
                    broker=order.get('broker_primary', ''),
                    order_id=order_id
                )
            except Exception as e:
                self._log(f"Notification error (cancelled): {e}")
        
        return result
    
    def shutdown(self):
        """Shutdown the service."""
        self._log("Shutting down...")
        self.is_running = False
        
        for order_id, task in list(self.monitor_tasks.items()):
            task.cancel()
        
        self.monitors.clear()
        self.monitor_tasks.clear()
        self.pending_orders.clear()
        self._price_reset_needed.clear()
        
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
