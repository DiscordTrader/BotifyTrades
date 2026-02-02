"""
Conditional Order Service
Monitors price conditions and executes orders when triggered.
"""

import os
import asyncio
import aiohttp
import threading
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import deque

try:
    import pytz
    IST = pytz.timezone('Asia/Kolkata')
except ImportError:
    IST = None

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_thread_logs = deque(maxlen=100)

def _log(msg: str, flush: bool = True):
    """Thread-safe logging that captures to both stdout and internal buffer."""
    if IST:
        timestamp = datetime.now(IST).strftime('%H:%M:%S')
    else:
        timestamp = datetime.now().strftime('%H:%M:%S')
    full_msg = f"[{timestamp}] {msg}"
    _thread_logs.append(full_msg)
    print(msg, flush=flush)

def get_thread_logs() -> list:
    """Get recent logs from the monitoring thread."""
    return list(_thread_logs)

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
    is_circuit_breaker_tripped,
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
        """Record an API call."""
        self.calls.append(datetime.now().timestamp())
        self._cleanup_old_calls()
    
    def _cleanup_old_calls(self):
        """Remove calls older than 1 minute."""
        cutoff = datetime.now().timestamp() - 60
        self.calls = [c for c in self.calls if c > cutoff]
    
    def get_usage_ratio(self) -> float:
        """Get current usage as a ratio (0.0 to 1.0)."""
        self._cleanup_old_calls()
        return len(self.calls) / self.max_calls_per_minute if self.max_calls_per_minute > 0 else 0
    
    def can_make_call(self) -> bool:
        """Check if we can make another API call."""
        return self.get_usage_ratio() < 1.0
    
    def should_fallback(self, threshold: float = 0.8) -> bool:
        """Check if we should fall back to another provider."""
        return self.get_usage_ratio() >= threshold


class PriceMonitor:
    """Base class for price monitoring."""
    
    def __init__(self, symbol: str, callback: Callable[[str, float], None]):
        self.symbol = symbol
        self.callback = callback
        self.is_running = False
        self.last_price = None
    
    async def start(self):
        """Start monitoring."""
        raise NotImplementedError
    
    async def stop(self):
        """Stop monitoring."""
        self.is_running = False


class FinnhubPriceMonitor(PriceMonitor):
    """Price monitor using Finnhub API."""
    
    def __init__(self, symbol: str, callback: Callable[[str, float], None], api_key: str):
        super().__init__(symbol, callback)
        self.api_key = api_key
        self.base_url = "https://finnhub.io/api/v1"
        self.poll_interval = 5  # seconds
    
    async def start(self):
        """Start polling Finnhub for price updates."""
        self.is_running = True
        print(f"[FINNHUB] Starting price monitor for {self.symbol}")
        
        async with aiohttp.ClientSession() as session:
            while self.is_running:
                try:
                    price = await self._fetch_price(session)
                    if price and price != self.last_price:
                        self.last_price = price
                        await self.callback(self.symbol, price)
                except Exception as e:
                    print(f"[FINNHUB] Error fetching price for {self.symbol}: {e}")
                
                await asyncio.sleep(self.poll_interval)
    
    async def _fetch_price(self, session: aiohttp.ClientSession) -> Optional[float]:
        """Fetch current price from Finnhub."""
        url = f"{self.base_url}/quote"
        params = {'symbol': self.symbol, 'token': self.api_key}
        
        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('c')  # Current price
        except Exception as e:
            print(f"[FINNHUB] Request error for {self.symbol}: {e}")
        
        return None


def _check_yfinance_available() -> bool:
    """Check if yfinance is available."""
    try:
        import yfinance
        return True
    except ImportError:
        return False


YFINANCE_AVAILABLE = _check_yfinance_available()


class YFinancePriceMonitor(PriceMonitor):
    """Price monitor using yfinance (free, no API key required)."""
    
    def __init__(self, symbol: str, callback: Callable[[str, float], None]):
        super().__init__(symbol, callback)
        self.poll_interval = 10  # seconds (be respectful to free API)
        self._yf_available = YFINANCE_AVAILABLE
        self._error_count = 0
        self._max_errors = 5
    
    async def start(self):
        """Start polling yfinance for price updates."""
        self.is_running = True
        
        if not self._yf_available:
            print(f"[YFINANCE] ERROR: yfinance not installed - install with: pip install yfinance")
            return
        
        print(f"[YFINANCE] Starting price monitor for {self.symbol}")
        
        while self.is_running:
            try:
                price = await self._fetch_price()
                if price and price != self.last_price:
                    self.last_price = price
                    self._error_count = 0  # Reset on success
                    await self.callback(self.symbol, price)
            except Exception as e:
                self._error_count += 1
                print(f"[YFINANCE] Error fetching price for {self.symbol}: {e}")
                if self._error_count >= self._max_errors:
                    print(f"[YFINANCE] Too many errors, stopping monitor for {self.symbol}")
                    break
            
            await asyncio.sleep(self.poll_interval)
    
    async def _fetch_price(self) -> Optional[float]:
        """Fetch current price from yfinance."""
        if not self._yf_available:
            return None
        
        try:
            import yfinance as yf
            loop = asyncio.get_event_loop()
            
            def get_fast_price():
                ticker = yf.Ticker(self.symbol)
                fast_info = ticker.fast_info
                return fast_info.get('lastPrice') or fast_info.get('regularMarketPrice')
            
            price = await loop.run_in_executor(None, get_fast_price)
            return float(price) if price else None
        except Exception as e:
            print(f"[YFINANCE] Request error for {self.symbol}: {e}")
            return None


class BrokerPriceMonitor(PriceMonitor):
    """Price monitor using broker API (Webull, Alpaca, etc.)."""
    
    def __init__(self, symbol: str, callback: Callable[[str, float], None], broker_name: str, broker_instance: Any = None):
        super().__init__(symbol, callback)
        self.broker_name = broker_name
        self.broker_instance = broker_instance
        self.poll_interval = 5  # seconds
    
    async def start(self):
        """Start polling broker for price updates."""
        import sys
        self.is_running = True
        sys.stderr.write(f"[{self.broker_name.upper()}] Starting price monitor for {self.symbol}\n")
        sys.stderr.flush()
        
        poll_count = 0
        while self.is_running:
            try:
                price = await self._fetch_price()
                poll_count += 1
                if poll_count <= 3 or poll_count % 10 == 0:
                    sys.stderr.write(f"[{self.broker_name.upper()}] Poll #{poll_count} for {self.symbol}: price={price}\n")
                    sys.stderr.flush()
                if price and price != self.last_price:
                    self.last_price = price
                    await self.callback(self.symbol, price)
            except Exception as e:
                sys.stderr.write(f"[{self.broker_name.upper()}] Error fetching price for {self.symbol}: {e}\n")
                sys.stderr.flush()
            
            await asyncio.sleep(self.poll_interval)
    
    async def _fetch_price(self) -> Optional[float]:
        """Fetch current price from broker."""
        if not self.broker_instance:
            return None
        
        try:
            loop = asyncio.get_event_loop()
            
            if self.broker_name.lower() == 'alpaca':
                from alpaca.data import StockHistoricalDataClient
                from alpaca.data.requests import StockLatestQuoteRequest
                
                if hasattr(self.broker_instance, 'api_key') and hasattr(self.broker_instance, 'secret_key'):
                    client = StockHistoricalDataClient(
                        self.broker_instance.api_key, 
                        self.broker_instance.secret_key
                    )
                    request = StockLatestQuoteRequest(symbol_or_symbols=self.symbol)
                    quotes = await loop.run_in_executor(None, lambda: client.get_stock_latest_quote(request))
                    if self.symbol in quotes:
                        return float(quotes[self.symbol].ask_price)
            
            elif self.broker_name.lower() == 'webull':
                if hasattr(self.broker_instance, 'get_quote'):
                    quote = await loop.run_in_executor(None, lambda: self.broker_instance.get_quote(self.symbol))
                    if quote and 'close' in quote:
                        return float(quote['close'])
            
            elif self.broker_name.lower() == 'upstox':
                if hasattr(self.broker_instance, 'get_quote'):
                    quote = await self.broker_instance.get_quote(self.symbol)
                    if quote and isinstance(quote, dict):
                        for key, data in quote.items():
                            if hasattr(data, 'last_price'):
                                return float(data.last_price)
                            elif isinstance(data, dict) and 'last_price' in data:
                                return float(data['last_price'])
            
            elif self.broker_name.lower() == 'schwab':
                if hasattr(self.broker_instance, 'get_quote'):
                    quote = await loop.run_in_executor(None, lambda: self.broker_instance.get_quote(self.symbol))
                    if quote:
                        if isinstance(quote, dict) and 'lastPrice' in quote:
                            return float(quote['lastPrice'])
                        elif hasattr(quote, 'lastPrice'):
                            return float(quote.lastPrice)
            
            elif self.broker_name.lower() == 'ibkr':
                if hasattr(self.broker_instance, 'get_quote'):
                    quote = await loop.run_in_executor(None, lambda: self.broker_instance.get_quote(self.symbol))
                    if quote:
                        if hasattr(quote, 'last') and quote.last:
                            return float(quote.last)
                        elif isinstance(quote, dict) and 'last' in quote:
                            return float(quote['last'])
                        elif isinstance(quote, dict) and 'close' in quote:
                            return float(quote['close'])
            
            elif self.broker_name.lower() == 'robinhood':
                if hasattr(self.broker_instance, 'get_quote'):
                    quote = await loop.run_in_executor(None, lambda: self.broker_instance.get_quote(self.symbol))
                    if quote and 'last_trade_price' in quote:
                        return float(quote['last_trade_price'])
            
            elif self.broker_name.lower() == 'tastytrade':
                if hasattr(self.broker_instance, 'get_quote'):
                    quote = await loop.run_in_executor(None, lambda: self.broker_instance.get_quote(self.symbol))
                    if quote:
                        if isinstance(quote, dict) and 'last' in quote:
                            return float(quote['last'])
                        elif hasattr(quote, 'last'):
                            return float(quote.last)
            
        except Exception as e:
            print(f"[{self.broker_name.upper()}] Quote error for {self.symbol}: {e}")
        
        return None


class IndiaPriceMonitor(PriceMonitor):
    """
    Price monitor for Indian markets (NSE options).
    Uses Upstox/Zerodha API with proper instrument key lookup.
    Falls back to yfinance for index prices if broker API fails.
    """
    
    def __init__(self, symbol: str, strike: float, opt_type: str, callback: Callable[[str, float], None], broker_instance: Any = None, expiry: str = None):
        super().__init__(symbol, callback)
        self.strike = strike
        self.opt_type = opt_type
        self.broker_instance = broker_instance
        self.expiry = expiry
        self.poll_interval = 2  # Upstox allows 25 req/sec, 250/min - 2s is safe and fast
        self._error_count = 0
        self._max_errors = 10
        self._instrument_key = None
        self._instrument_key_lookup_done = False
        self._poll_count = 0  # Track polls for periodic logging
    
    def _get_underlying_key(self) -> str:
        """Get Upstox underlying key for NSE indices."""
        index_map = {
            'NIFTY': 'NSE_INDEX|Nifty 50',
            'BANKNIFTY': 'NSE_INDEX|Nifty Bank',
            'FINNIFTY': 'NSE_INDEX|Nifty Fin Service',
            'SENSEX': 'BSE_INDEX|SENSEX',
        }
        return index_map.get(self.symbol.upper(), f'NSE_EQ|{self.symbol}')
    
    async def _lookup_instrument_key(self) -> Optional[str]:
        """Look up actual Upstox instrument key from option contracts API."""
        if self._instrument_key_lookup_done:
            return self._instrument_key
        
        self._instrument_key_lookup_done = True
        
        if not self.broker_instance:
            print(f"[INDIA] No broker instance for instrument lookup")
            return None
        
        try:
            import requests
            from urllib.parse import quote
            from datetime import datetime
            
            underlying_key = self._get_underlying_key()
            access_token = self.broker_instance.config.get('access_token') if hasattr(self.broker_instance, 'config') else None
            
            if not access_token:
                print(f"[INDIA] No access token for instrument lookup")
                return None
            
            expiry_date = self._format_expiry_to_date(self.expiry) if self.expiry else self._get_next_expiry()
            opt_type_str = 'CE' if self.opt_type == 'C' else 'PE'
            
            encoded_key = quote(underlying_key, safe='')
            url = f"https://api.upstox.com/v2/option/contract?instrument_key={encoded_key}&expiry_date={expiry_date}"
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json'
            }
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, lambda: requests.get(url, headers=headers, timeout=10))
            
            if response.status_code != 200:
                print(f"[INDIA] Option contracts API error: {response.status_code}")
                return None
            
            data = response.json()
            if data.get('status') != 'success':
                print(f"[INDIA] API error: {data}")
                return None
            
            contracts = data.get('data', [])
            expiry_contracts = [c for c in contracts if c.get('expiry') == expiry_date]
            
            print(f"[INDIA] Found {len(expiry_contracts)} contracts for {self.symbol} {expiry_date}")
            
            for contract in expiry_contracts:
                if (contract.get('strike_price') == self.strike and 
                    contract.get('instrument_type') == opt_type_str):
                    self._instrument_key = contract.get('instrument_key')
                    print(f"[INDIA] ✓ Resolved instrument key: {self._instrument_key}")
                    return self._instrument_key
            
            print(f"[INDIA] ⚠️ No exact match for {self.symbol} {self.strike} {opt_type_str}")
            return None
            
        except Exception as e:
            print(f"[INDIA] Instrument lookup error: {e}")
            return None
    
    def _format_expiry_to_date(self, expiry: str) -> str:
        """Convert expiry to YYYY-MM-DD format. Uses IST timezone."""
        from datetime import datetime
        import re
        
        if not expiry:
            return self._get_next_expiry()
        
        try:
            if re.match(r'^\d{1,2}/\d{1,2}$', expiry):
                month, day = expiry.split('/')
                if IST:
                    year = datetime.now(IST).year
                else:
                    year = datetime.now().year
                return f"{year}-{int(month):02d}-{int(day):02d}"
            elif re.match(r'^\d{4}-\d{2}-\d{2}$', expiry):
                return expiry
        except Exception:
            pass
        
        return self._get_next_expiry()
    
    def _get_next_expiry(self) -> str:
        """Get next Tuesday expiry for NSE weekly options (effective Sept 2025).
        Uses IST timezone for correct expiry calculation.
        """
        from datetime import datetime, timedelta
        
        if IST:
            now = datetime.now(IST)
        else:
            now = datetime.now()
        
        days_ahead = 1 - now.weekday()
        if days_ahead < 0:
            days_ahead += 7
        elif days_ahead == 0 and now.hour >= 15:
            days_ahead = 7
        
        next_tuesday = now + timedelta(days=days_ahead)
        return next_tuesday.strftime("%Y-%m-%d")
    
    async def start(self) -> bool:
        """Start polling for price updates. Returns False if contract lookup failed."""
        self.is_running = True
        _log(f"[INDIA] Starting price monitor for {self.symbol} {self.strike}{self.opt_type}")
        
        instrument_key = await self._lookup_instrument_key()
        if instrument_key:
            _log(f"[INDIA] Monitoring option premium via {instrument_key}")
        else:
            _log(f"[INDIA] ❌ No instrument key - cannot monitor option premium")
            self.is_running = False
            return False
        
        while self.is_running and self._error_count < self._max_errors:
            try:
                self._poll_count += 1
                price = await self._fetch_price()
                if price:
                    price_changed = price != self.last_price
                    self.last_price = price
                    self._error_count = 0
                    if price_changed:
                        await self.callback(self.symbol, price)
            except Exception as e:
                self._error_count += 1
                _log(f"[INDIA] Error fetching price for {self.symbol}: {e}")
            
            await asyncio.sleep(self.poll_interval)
        
        if self._error_count >= self._max_errors:
            _log(f"[INDIA] Too many errors, stopping monitor for {self.symbol}")
    
    async def _fetch_price(self) -> Optional[float]:
        """Fetch option premium from broker using resolved instrument key."""
        if self._instrument_key and self.broker_instance:
            try:
                if hasattr(self.broker_instance, 'get_ltp'):
                    ltp = await self.broker_instance.get_ltp(self._instrument_key)
                    if ltp:
                        _log(f"[INDIA] Price: {self.symbol} {self.strike}{self.opt_type} = ₹{ltp:.2f}")
                        return float(ltp)
                    else:
                        _log(f"[INDIA] ⚠️ LTP returned None/0 for {self._instrument_key}")
                
                if hasattr(self.broker_instance, 'get_quote'):
                    quote = await self.broker_instance.get_quote(self._instrument_key)
                    if quote and isinstance(quote, dict):
                        for key, data in quote.items():
                            if hasattr(data, 'last_price'):
                                ltp = float(data.last_price)
                                print(f"[INDIA] Quote LTP for {self._instrument_key}: ₹{ltp:.2f}")
                                return ltp
                            elif isinstance(data, dict) and 'last_price' in data:
                                ltp = float(data['last_price'])
                                print(f"[INDIA] Quote LTP for {self._instrument_key}: ₹{ltp:.2f}")
                                return ltp
            except Exception as e:
                print(f"[INDIA] Broker quote failed for {self._instrument_key}: {e}")
        
        print(f"[INDIA] ⚠️ No option premium available for {self.symbol} {self.strike}{self.opt_type} - broker API required")
        return None


class ConditionalOrderService:
    """
    Main service for managing conditional orders.
    
    Features:
    - Price monitoring with broker-native and Finnhub fallback
    - Automatic order execution when trigger conditions are met
    - Integration with existing position sizing and risk management
    - Support for multiple simultaneous conditional orders
    """
    
    def __init__(self):
        self.is_running = False
        self.monitors: Dict[int, PriceMonitor] = {}
        self.monitor_tasks: Dict[int, asyncio.Task] = {}  # Track background monitoring tasks
        self.rate_limiters: Dict[str, RateLimitTracker] = {}
        self.pending_orders: Dict[int, Dict] = {}
        self.finnhub_api_key = os.getenv('FINNHUB_API_KEY', '')
        self.broker_instances: Dict[str, Any] = {}  # broker_name -> broker instance
        self.execution_callback: Optional[Callable] = None
        self.notification_callback: Optional[Callable] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        
        self._init_rate_limiters()
    
    def set_broker_instance(self, broker_name: str, instance: Any):
        """Register a broker instance for price monitoring."""
        self.broker_instances[broker_name.lower()] = instance
        print(f"[CONDITIONAL] Registered broker: {broker_name}")
    
    def _init_rate_limiters(self):
        """Initialize rate limiters for each broker/provider."""
        self.rate_limiters = {
            'webull': RateLimitTracker('webull', 120),
            'alpaca': RateLimitTracker('alpaca', 200),
            'tastytrade': RateLimitTracker('tastytrade', 60),
            'ibkr': RateLimitTracker('ibkr', 100),
            'finnhub': RateLimitTracker('finnhub', 60),
            'zerodha': RateLimitTracker('zerodha', 180),
            'upstox': RateLimitTracker('upstox', 250),
            'dhanq': RateLimitTracker('dhanq', 60),
        }
    
    def is_enabled(self) -> bool:
        """Check if conditional order service is enabled globally."""
        settings = get_conditional_order_settings()
        return settings.get('enabled', False)
    
    def get_settings(self) -> Dict[str, Any]:
        """Get global service settings."""
        return get_conditional_order_settings()
    
    def update_settings(self, settings: Dict[str, Any]) -> bool:
        """Update global service settings."""
        return save_conditional_order_settings(settings)
    
    def set_execution_callback(self, callback: Callable):
        """Set callback for order execution."""
        self.execution_callback = callback
    
    def set_notification_callback(self, callback: Callable):
        """Set callback for notifications."""
        self.notification_callback = callback
    
    def _get_order_by_message_id(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Check if a conditional order already exists for this message_id."""
        try:
            from gui_app.database import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, symbol, status FROM conditional_orders 
                WHERE original_message LIKE ? AND status NOT IN ('TERMINATED', 'CANCELED', 'EXPIRED')
            ''', (f'%message_id={message_id}%',))
            row = cursor.fetchone()
            if row:
                return {'id': row[0], 'symbol': row[1], 'status': row[2]}
            
            # Also check signal_id field
            cursor.execute('''
                SELECT id, symbol, status FROM conditional_orders 
                WHERE signal_id = ? AND status NOT IN ('TERMINATED', 'CANCELED', 'EXPIRED')
            ''', (message_id,))
            row = cursor.fetchone()
            if row:
                return {'id': row[0], 'symbol': row[1], 'status': row[2]}
            
            return None
        except Exception as e:
            print(f"[CONDITIONAL] Error checking for duplicate: {e}")
            return None
    
    def create_order(
        self,
        channel_id: str,
        parsed_signal: Dict[str, Any],
        broker: str
    ) -> Optional[int]:
        """
        Create a new conditional order from a parsed signal.
        
        Args:
            channel_id: Discord/Telegram channel ID
            parsed_signal: Parsed conditional signal dict
            broker: Primary broker for execution (from caller or channel override)
        
        Returns:
            Order ID if created, None if failed
        """
        if not self.is_enabled():
            print("[CONDITIONAL] Service is disabled")
            return None
        
        # Deduplication: Check if order already exists for this message
        message_id = parsed_signal.get('message_id')
        if message_id:
            # Check if we already have an order for this message_id
            existing = self._get_order_by_message_id(message_id)
            if existing:
                print(f"[CONDITIONAL] ⚠️ Duplicate order request for message {message_id} - skipping")
                return existing.get('id')  # Return existing order ID
        
        channel_settings = get_channel_conditional_settings(channel_id)
        if not channel_settings.get('conditional_order_enabled', True):
            print(f"[CONDITIONAL] Conditional orders disabled for channel {channel_id}")
            return None
        
        effective_broker = channel_settings.get('broker_override') or broker
        if not effective_broker:
            print(f"[CONDITIONAL] No broker configured for channel {channel_id} and none passed")
            return None
        
        # Get trigger offset: channel-specific first, then fallback to global settings
        trigger_offset = channel_settings.get('trigger_offset_percent', 0.0) or 0.0
        print(f"[CONDITIONAL] Channel {channel_id} trigger_offset_percent from settings: {trigger_offset}", flush=True)
        if trigger_offset == 0:
            # Fallback to global conditional order settings
            try:
                from gui_app.database import get_conditional_order_settings
                global_settings = get_conditional_order_settings()
                trigger_offset = float(global_settings.get('trigger_offset_percent', 0) or 0)
                if trigger_offset != 0:
                    print(f"[CONDITIONAL] Using GLOBAL trigger offset: {trigger_offset}%")
            except Exception as e:
                print(f"[CONDITIONAL] Could not load global offset: {e}")
                trigger_offset = 0.0
        
        trigger_price = parsed_signal.get('trigger_price', 0)
        trigger_type = parsed_signal.get('trigger_type', 'over')
        
        if trigger_offset != 0:
            if trigger_type == 'over':
                adjusted_price = trigger_price * (1 + trigger_offset / 100)
                print(f"[CONDITIONAL] ✓ Applied +{trigger_offset}% offset: ${trigger_price} -> ${adjusted_price:.4f}", flush=True)
            else:  # under
                adjusted_price = trigger_price * (1 - trigger_offset / 100)
                print(f"[CONDITIONAL] ✓ Applied -{trigger_offset}% offset: ${trigger_price} -> ${adjusted_price:.4f}", flush=True)
        else:
            adjusted_price = trigger_price
            print(f"[CONDITIONAL] No offset applied, adjusted_price = trigger_price = ${trigger_price}", flush=True)
        
        # Channel-level timeout in minutes takes priority (NULL = use legacy expiry setting)
        # order_timeout_minutes applies to ALL orders, conditional_order_timeout_minutes is legacy/specific
        timeout_minutes = channel_settings.get('order_timeout_minutes') or channel_settings.get('conditional_order_timeout_minutes')
        if timeout_minutes:
            # Explicit timeout configured: X minutes from entry
            expires_at = self._calculate_expiry_minutes(timeout_minutes)
            print(f"[CONDITIONAL] Using channel timeout: {timeout_minutes} min from entry (applies to all orders)")
        else:
            # No timeout configured - use legacy expiry setting or no expiry
            expiry = channel_settings.get('conditional_order_expiry')
            if expiry:
                expires_at = self._calculate_expiry(expiry)
            else:
                # No expiry configured - order stays active indefinitely
                expires_at = None
                print(f"[CONDITIONAL] No timeout configured for channel - order has no expiry")
        
        # Position sizing: signal first, then channel settings
        size_mode = parsed_signal.get('size_mode')
        qty_value = None
        params_source = 'signal'
        
        if size_mode == 'percent_account':
            qty_value = parsed_signal.get('position_size_pct')
        elif size_mode == 'fixed_qty':
            qty_value = parsed_signal.get('fixed_qty')
        else:
            # Fall back to channel settings
            params_source = 'channel'
            if channel_settings.get('position_size_pct'):
                size_mode = 'percent_account'
                qty_value = channel_settings.get('position_size_pct')
                print(f"[CONDITIONAL] Using channel position_size_pct: {qty_value}%")
            elif channel_settings.get('default_quantity'):
                size_mode = 'fixed_qty'
                qty_value = channel_settings.get('default_quantity')
                print(f"[CONDITIONAL] Using channel default_quantity: {qty_value}")
        
        # Profit targets: signal first, then channel settings
        profit_targets = parsed_signal.get('profit_targets', [])
        if not profit_targets:
            # Build profit targets from channel risk settings
            channel_targets = []
            for i in range(1, 5):
                pt_pct = channel_settings.get(f'profit_target_{i}_pct')
                if pt_pct and pt_pct > 0:
                    channel_targets.append(pt_pct)
            if channel_targets:
                profit_targets = channel_targets
                print(f"[CONDITIONAL] Using channel profit targets: {profit_targets}")
        
        take_profit_json = json.dumps(profit_targets) if profit_targets else None
        
        # Stop loss: signal first, then channel settings
        stop_loss = parsed_signal.get('stop_loss')
        stop_loss_type = parsed_signal.get('stop_loss_type')
        stop_loss_value = parsed_signal.get('stop_loss_value') or stop_loss
        
        if not stop_loss_value and channel_settings.get('stop_loss_pct'):
            stop_loss_type = 'percent'
            stop_loss_value = channel_settings.get('stop_loss_pct')
            print(f"[CONDITIONAL] Using channel stop_loss_pct: {stop_loss_value}%")
        
        market = parsed_signal.get('market', 'US')
        strike = parsed_signal.get('strike')
        opt_type = parsed_signal.get('opt_type')
        option_expiry = parsed_signal.get('expiry')
        
        # Only use lot_size/lots for Indian markets - US uses contracts/qty
        lot_size = parsed_signal.get('lot_size') if market == 'INDIA' else None
        lots = parsed_signal.get('lots') if market == 'INDIA' else None
        
        order_id = create_conditional_order(
            channel_id=channel_id,
            symbol=parsed_signal.get('symbol', ''),
            trigger_type=trigger_type,
            trigger_price=trigger_price,
            adjusted_trigger_price=adjusted_price,
            broker_primary=effective_broker,
            stop_loss_type=stop_loss_type,
            stop_loss_value=stop_loss_value,
            take_profit_targets=take_profit_json,
            size_mode=size_mode,
            qty_value=qty_value,
            params_source=params_source,
            expires_at=expires_at,
            original_message=parsed_signal.get('_original_message', ''),
            asset_type=parsed_signal.get('asset_type', 'stock'),
            signal_id=message_id,  # Store message_id for deduplication
            strike=strike,
            opt_type=opt_type,
            market=market,
            expiry=option_expiry,
            lot_size=lot_size,
            lots=lots,
        )
        
        if order_id:
            print(f"[CONDITIONAL] Created order #{order_id} for {parsed_signal.get('symbol')}")
            self._schedule_monitoring(order_id)
        
        return order_id
    
    def _calculate_expiry_minutes(self, minutes: int) -> str:
        """Calculate expiry datetime from now + X minutes (channel-level timeout)."""
        now = datetime.now()
        expiry = now + timedelta(minutes=minutes)
        return expiry.strftime('%Y-%m-%d %H:%M:%S')
    
    def _calculate_expiry(self, expiry_setting: str) -> str:
        """Calculate expiry datetime based on legacy setting."""
        now = datetime.now()
        
        if expiry_setting == 'end_of_day':
            expiry = now.replace(hour=16, minute=0, second=0, microsecond=0)
            if expiry <= now:
                expiry = expiry + timedelta(days=1)
        elif expiry_setting == '1_hour':
            expiry = now + timedelta(hours=1)
        elif expiry_setting == '4_hours':
            expiry = now + timedelta(hours=4)
        elif expiry_setting == '1_day':
            expiry = now + timedelta(days=1)
        else:
            # Unknown setting - no expiry
            return None
        
        return expiry.strftime('%Y-%m-%d %H:%M:%S')
    
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
        
        if self.is_running and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._start_monitor(order_id, order),
                self._loop
            )
    
    async def _start_monitor(self, order_id: int, order: Dict):
        """Start a price monitor for an order.
        
        Priority: Broker API -> Finnhub -> yfinance
        For India orders: India broker API (Upstox/Zerodha) -> yfinance
        """
        import sys
        symbol = order['symbol']
        broker = order['broker_primary']
        market = order.get('market', 'US')
        sys.stderr.write(f"[CONDITIONAL] _start_monitor called for #{order_id} {symbol} broker={broker} market={market}\n")
        sys.stderr.flush()
        
        try:
            settings = get_conditional_order_settings()
            threshold = settings.get('rate_limit_threshold', 80) / 100
            
            rate_limiter = self.rate_limiters.get(broker.lower()) if broker else None
            broker_instance = self.broker_instances.get(broker.lower()) if broker else None
            broker_rate_ok = rate_limiter and not rate_limiter.should_fallback(threshold)
            finnhub_available = bool(self.finnhub_api_key)
            
            sys.stderr.write(f"[CONDITIONAL] broker_instance={broker_instance is not None}, rate_ok={broker_rate_ok}, finnhub={finnhub_available}\n")
            sys.stderr.flush()
        except Exception as e:
            sys.stderr.write(f"[CONDITIONAL] ❌ Error in setup: {e}\n")
            sys.stderr.flush()
            import traceback
            traceback.print_exc()
            return
        
        monitor = None
        data_source = None
        
        async def price_callback(sym: str, price: float):
            await self._on_price_update(order_id, sym, price)
        
        if market == 'INDIA':
            strike = order.get('strike', 0)
            opt_type = order.get('opt_type', 'C')
            expiry = order.get('expiry')
            sys.stderr.write(f"[CONDITIONAL] INDIA market detected: strike={strike}, opt_type={opt_type}, expiry={expiry}\n")
            sys.stderr.flush()
            
            india_brokers = ['upstox', 'zerodha', 'dhanq']
            india_broker_instance = None
            india_broker_name = None
            
            for india_broker in india_brokers:
                if india_broker in self.broker_instances:
                    india_broker_instance = self.broker_instances[india_broker]
                    india_broker_name = india_broker
                    sys.stderr.write(f"[CONDITIONAL] Found India broker: {india_broker_name}\n")
                    sys.stderr.flush()
                    break
            
            sys.stderr.write(f"[CONDITIONAL] Using IndiaPriceMonitor for {symbol} {strike}{opt_type} expiry={expiry} (broker: {india_broker_name or 'fallback'})\n")
            sys.stderr.flush()
            monitor = IndiaPriceMonitor(
                symbol,
                strike,
                opt_type,
                price_callback,
                india_broker_instance,
                expiry
            )
            data_source = india_broker_name or 'yfinance'
            update_conditional_order_status(
                order_id,
                'ACTIVE_MONITORING',
                data_source_active=data_source,
                event='INDIA_MONITOR_STARTED',
                details=f"Monitoring {symbol} {strike}{opt_type}"
            )
        elif broker_instance and broker_rate_ok:
            data_source = broker.lower()
            sys.stderr.write(f"[CONDITIONAL] Using broker {broker} for price monitoring of {symbol}\n")
            sys.stderr.flush()
            monitor = BrokerPriceMonitor(
                symbol,
                price_callback,
                broker,
                broker_instance
            )
            update_conditional_order_status(
                order_id,
                'ACTIVE_MONITORING',
                data_source_active=broker.lower()
            )
        elif finnhub_available:
            data_source = 'finnhub'
            fallback_reason = 'broker_rate_limit' if (rate_limiter and rate_limiter.should_fallback(threshold)) else 'no_broker_instance'
            sys.stderr.write(f"[CONDITIONAL] Using Finnhub for price monitoring of {symbol} (reason: {fallback_reason})\n")
            sys.stderr.flush()
            monitor = FinnhubPriceMonitor(
                symbol,
                price_callback,
                self.finnhub_api_key
            )
            update_conditional_order_status(
                order_id,
                'FALLBACK_MONITORING',
                data_source_active='finnhub',
                fallback_reason=fallback_reason
            )
        elif YFINANCE_AVAILABLE:
            data_source = 'yfinance'
            sys.stderr.write(f"[CONDITIONAL] Using yfinance for price monitoring of {symbol} (delayed ~15min)\n")
            sys.stderr.flush()
            monitor = YFinancePriceMonitor(
                symbol,
                price_callback
            )
            update_conditional_order_status(
                order_id,
                'FALLBACK_MONITORING',
                data_source_active='yfinance',
                fallback_reason='no_api_key'
            )
        else:
            print(f"[CONDITIONAL] ERROR: No price source available for {symbol}")
            print(f"[CONDITIONAL]   - Set FINNHUB_API_KEY for reliable price data")
            print(f"[CONDITIONAL]   - Or install yfinance: pip install yfinance")
            update_conditional_order_status(
                order_id,
                'ERROR',
                event='NO_PRICE_SOURCE',
                error_message='No price source available. Set FINNHUB_API_KEY or install yfinance.'
            )
            return
        
        self.monitors[order_id] = monitor
        
        def _on_monitor_done(task: asyncio.Task, oid: int = order_id):
            """Callback when monitor task completes (success, error, or cancelled)."""
            try:
                result = task.result()
                if result is False:
                    print(f"[CONDITIONAL] ❌ Order #{oid}: Contract lookup failed - cannot monitor")
                    update_conditional_order_status(
                        oid,
                        'ERROR',
                        event='CONTRACT_LOOKUP_FAILED',
                        error_message='No matching contract found for this expiry/strike. Check if the contract exists.'
                    )
                    if oid in self.monitors:
                        del self.monitors[oid]
                    if oid in self.pending_orders:
                        del self.pending_orders[oid]
                    if oid in self.monitor_tasks:
                        del self.monitor_tasks[oid]
            except asyncio.CancelledError:
                print(f"[CONDITIONAL] Monitor #{oid} cancelled")
            except Exception as e:
                print(f"[CONDITIONAL] Monitor error for order #{oid}: {e}")
                update_conditional_order_status(
                    oid,
                    'ERROR',
                    event='MONITOR_ERROR',
                    error_message=str(e)
                )
        
        task = asyncio.create_task(monitor.start())
        task.add_done_callback(lambda t: _on_monitor_done(t, order_id))
        self.monitor_tasks[order_id] = task
        sys.stderr.write(f"[CONDITIONAL] ✓ Started background monitor task for order #{order_id}\n")
        sys.stderr.flush()
    
    async def _on_price_update(self, order_id: int, symbol: str, price: float):
        """Handle price update from monitor."""
        import sys
        sys.stderr.write(f"[CONDITIONAL] Price update received: #{order_id} {symbol} @ ₹{price:.2f}\n")
        sys.stderr.flush()
        
        order = self.pending_orders.get(order_id)
        if not order:
            sys.stderr.write(f"[CONDITIONAL] ⚠️ Order #{order_id} not in pending_orders!\n")
            sys.stderr.flush()
            return
        
        # Reload adjusted_trigger_price from database to pick up GUI offset changes
        fresh_order = get_conditional_order_by_id(order_id)
        if fresh_order:
            trigger_price = fresh_order.get('adjusted_trigger_price') or fresh_order.get('trigger_price')
            # Update cached order with fresh adjusted price
            order['adjusted_trigger_price'] = fresh_order.get('adjusted_trigger_price')
        else:
            trigger_price = order.get('adjusted_trigger_price') or order.get('trigger_price')
        trigger_type = order.get('trigger_type', 'over')
        
        sys.stderr.write(f"[CONDITIONAL] Checking trigger: {trigger_type} {trigger_price}, current={price:.2f}\n")
        sys.stderr.flush()
        
        triggered = False
        if trigger_type == 'over' and price >= trigger_price:
            triggered = True
        elif trigger_type == 'under' and price <= trigger_price:
            triggered = True
        
        if triggered:
            sys.stderr.write(f"[CONDITIONAL] 🎯 TRIGGERED! {symbol} @ ₹{price:.2f} (target: ₹{trigger_price:.2f})\n")
            sys.stderr.flush()
            sys.stderr.write(f"[CONDITIONAL] About to call _execute_order for #{order_id}\n")
            sys.stderr.flush()
            try:
                await self._execute_order(order_id, price)
                sys.stderr.write(f"[CONDITIONAL] _execute_order completed for #{order_id}\n")
                sys.stderr.flush()
            except Exception as e:
                sys.stderr.write(f"[CONDITIONAL] ❌ _execute_order EXCEPTION for #{order_id}: {e}\n")
                sys.stderr.flush()
                import traceback
                traceback.print_exc()
    
    async def _execute_order(self, order_id: int, triggered_price: float):
        """Execute a triggered conditional order."""
        import sys
        sys.stderr.write(f"[CONDITIONAL] _execute_order called for #{order_id} @ {triggered_price}\n")
        sys.stderr.flush()
        
        circuit_status = is_circuit_breaker_tripped()
        if circuit_status.get('tripped'):
            reason = circuit_status.get('reason', 'Circuit breaker tripped')
            sys.stderr.write(f"[CONDITIONAL] ⛔ BLOCKED by circuit breaker: {reason}\n")
            sys.stderr.flush()
            update_conditional_order_status(
                order_id,
                'BLOCKED',
                event='CIRCUIT_BREAKER',
                error_message=f"Trading halted: {reason}"
            )
            return
        
        if order_id in self.monitors:
            await self.monitors[order_id].stop()
            del self.monitors[order_id]
        
        if order_id in self.monitor_tasks:
            task = self.monitor_tasks[order_id]
            if not task.done():
                task.cancel()
            del self.monitor_tasks[order_id]
        
        update_conditional_order_status(
            order_id,
            'TRIGGERED',
            event='PRICE_TRIGGERED',
            details=f"Price triggered at ${triggered_price:.2f}"
        )
        
        order = get_conditional_order_by_id(order_id)
        if not order:
            sys.stderr.write(f"[CONDITIONAL] ❌ Order #{order_id} not found in database!\n")
            sys.stderr.flush()
            return
        
        sys.stderr.write(f"[CONDITIONAL] Order #{order_id} retrieved, callback={self.execution_callback is not None}\n")
        sys.stderr.flush()
        
        if self.execution_callback:
            try:
                update_conditional_order_status(order_id, 'EXECUTING')
                sys.stderr.write(f"[CONDITIONAL] Calling execution callback for #{order_id}...\n")
                sys.stderr.flush()
                success = await self.execution_callback(order, triggered_price)
                sys.stderr.write(f"[CONDITIONAL] Callback returned: {success}\n")
                sys.stderr.flush()
                
                if success:
                    update_conditional_order_status(
                        order_id,
                        'EXECUTED',
                        event='EXECUTION_SUCCESS',
                        details='Order executed successfully'
                    )
                    
                    await self._seed_risk_settings_after_execution(order, triggered_price)
                else:
                    update_conditional_order_status(
                        order_id,
                        'ERROR',
                        event='EXECUTION_FAILED',
                        error_message='Order execution failed'
                    )
            except Exception as e:
                sys.stderr.write(f"[CONDITIONAL] Execution error for order #{order_id}: {e}\n")
                sys.stderr.flush()
                update_conditional_order_status(
                    order_id,
                    'ERROR',
                    event='EXECUTION_ERROR',
                    error_message=str(e)
                )
        
        if order_id in self.pending_orders:
            del self.pending_orders[order_id]
        
        if self.notification_callback:
            await self.notification_callback(order, triggered_price, 'TRIGGERED')
    
    async def _seed_risk_settings_after_execution(self, order: dict, entry_price: float):
        """
        Seed SL/PT settings from conditional order into position cache after execution.
        This ensures RiskManager picks up the configured stops and targets.
        
        Example: "@Daytrades APVO over 13.25 / SL 9% / profits 14.45-16"
        After trigger, seeds:
        - Stop loss price at entry_price * (1 - 0.09)
        - Profit targets at $14.45, $16
        """
        import sys
        try:
            symbol = order.get('symbol', '')
            broker = order.get('broker_primary', 'unknown')
            order_id = order.get('id')
            
            sl_pct = order.get('stop_loss_pct') or order.get('stop_loss_value')
            sl_fixed = order.get('stop_loss_fixed')
            sl_type = order.get('stop_loss_type', 'pct')
            
            profit_targets_raw = order.get('take_profit_targets') or order.get('target_ranges')
            trailing_enabled = bool(order.get('trailing_stop_enabled'))
            leave_runner = bool(order.get('leave_runner'))
            
            sl_price = None
            if sl_fixed and sl_type == 'fixed':
                sl_price = float(sl_fixed)
            elif sl_pct:
                sl_price = entry_price * (1 - float(sl_pct) / 100)
            
            pt_prices = []
            if profit_targets_raw:
                import json
                try:
                    if isinstance(profit_targets_raw, str):
                        pts = json.loads(profit_targets_raw)
                    else:
                        pts = profit_targets_raw
                    
                    if isinstance(pts, list):
                        for pt in pts:
                            if isinstance(pt, (int, float)):
                                pt_prices.append(float(pt))
                            elif isinstance(pt, dict) and 'price' in pt:
                                pt_prices.append(float(pt['price']))
                    elif isinstance(pts, dict):
                        for key in ['pt1', 'pt2', 'pt3', 'pt4', 'target1', 'target2']:
                            if key in pts and pts[key]:
                                pt_prices.append(float(pts[key]))
                except (json.JSONDecodeError, TypeError, ValueError) as e:
                    sys.stderr.write(f"[CONDITIONAL] Failed to parse profit targets: {e}\n")
            
            if sl_price or pt_prices:
                sys.stderr.write(f"[CONDITIONAL] 🎯 Seeding risk settings for {symbol}:\n")
                if sl_price:
                    sys.stderr.write(f"[CONDITIONAL]   SL: ${sl_price:.2f} (entry: ${entry_price:.2f})\n")
                if pt_prices:
                    sys.stderr.write(f"[CONDITIONAL]   PT: {pt_prices}\n")
                sys.stderr.flush()
                
                try:
                    from src.risk.position_cache import PositionCache
                    
                    qty = order.get('calculated_qty') or order.get('qty_value') or 1
                    asset_type = order.get('asset_type', 'stock')
                    channel_id = order.get('channel_id')
                    
                    broker_upper = broker.upper() if broker else 'UNKNOWN'
                    if asset_type == 'option':
                        strike = order.get('strike')
                        expiry = order.get('expiry')
                        opt_type = order.get('opt_type', 'C')
                        position_key = f"{broker_upper}_{symbol}_{strike}_{expiry}_{opt_type}"
                    else:
                        position_key = f"{broker_upper}_{symbol}_stock"
                    
                    cache = PositionCache()
                    
                    cache_data = {
                        'symbol': symbol,
                        'entry_price': entry_price,
                        'quantity': int(qty),
                        'broker': broker_upper,
                        'channel_id': str(channel_id) if channel_id else None,
                        'conditional_order_id': order_id,
                        'stop_loss_price': sl_price,
                        'stop_loss_pct': float(sl_pct) if sl_pct else None,
                        'profit_targets': pt_prices if pt_prices else None,
                        'trailing_enabled': trailing_enabled,
                        'leave_runner': leave_runner,
                        'asset_type': asset_type,
                    }
                    
                    cache.set(position_key, cache_data)
                    sl_display = f"${sl_price:.2f}" if sl_price else "None"
                    sys.stderr.write(f"[CONDITIONAL] ✓ Seeded position cache: {position_key} with SL={sl_display} PT={pt_prices}\n")
                    sys.stderr.flush()
                    
                except Exception as e:
                    sys.stderr.write(f"[CONDITIONAL] ⚠️ Failed to seed position cache: {e}\n")
                    sys.stderr.flush()
            else:
                sys.stderr.write(f"[CONDITIONAL] No SL/PT settings to seed for {symbol}\n")
                sys.stderr.flush()
                
        except Exception as e:
            sys.stderr.write(f"[CONDITIONAL] Error seeding risk settings: {e}\n")
            sys.stderr.flush()
            import traceback
            traceback.print_exc()
    
    def cancel_order(self, order_id: int, reason: str = 'User cancelled') -> bool:
        """Cancel a conditional order."""
        if order_id in self.monitors:
            asyncio.run_coroutine_threadsafe(
                self.monitors[order_id].stop(),
                self._loop
            )
            del self.monitors[order_id]
        
        if order_id in self.monitor_tasks:
            task = self.monitor_tasks[order_id]
            if not task.done():
                task.cancel()
            del self.monitor_tasks[order_id]
        
        if order_id in self.pending_orders:
            del self.pending_orders[order_id]
        
        return cancel_conditional_order(order_id, reason)
    
    def start(self):
        """Start the conditional order service."""
        import sys
        sys.stderr.write("[CONDITIONAL] start() called\n")
        sys.stderr.flush()
        print("[CONDITIONAL] start() called", flush=True)
        
        if self.is_running:
            print("[CONDITIONAL] Service already running", flush=True)
            return
        
        if not self.is_enabled():
            print("[CONDITIONAL] Service is disabled in settings", flush=True)
            return
        
        print("[CONDITIONAL] Creating service thread...", flush=True)
        sys.stderr.write("[CONDITIONAL] Creating thread...\n")
        self.is_running = True
        
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True, name="ConditionalOrderService")
        self._thread.start()
        
        import time
        time.sleep(0.5)
        
        if self._thread.is_alive():
            print(f"[CONDITIONAL] ✓ Service thread started (ID: {self._thread.ident})", flush=True)
        else:
            print("[CONDITIONAL] ❌ Service thread failed to start", flush=True)
        sys.stdout.flush()
    
    def _run_event_loop(self):
        """Run the asyncio event loop in a separate thread."""
        import sys
        import logging
        logger = logging.getLogger(__name__)
        
        sys.stderr.write("[CONDITIONAL] Starting event loop thread...\n")
        sys.stderr.flush()
        
        try:
            sys.stderr.write("[CONDITIONAL] Creating new event loop...\n")
            sys.stderr.flush()
            self._loop = asyncio.new_event_loop()
            sys.stderr.write("[CONDITIONAL] Setting event loop...\n")
            sys.stderr.flush()
            asyncio.set_event_loop(self._loop)
            sys.stderr.write("[CONDITIONAL] Running _main_loop...\n")
            sys.stderr.flush()
            self._loop.run_until_complete(self._main_loop())
        except Exception as e:
            sys.stderr.write(f"[CONDITIONAL] ❌ Event loop error: {e}\n")
            sys.stderr.flush()
            import traceback
            traceback.print_exc()
        finally:
            if self._loop:
                self._loop.close()
            sys.stderr.write("[CONDITIONAL] Event loop closed\n")
            sys.stderr.flush()
    
    async def _main_loop(self):
        """Main service loop with enable gate and pending order check."""
        import sys
        import time
        sys.stderr.write("[CONDITIONAL] _main_loop starting...\n")
        sys.stderr.flush()
        
        self._standby_mode = False
        self._last_status_log = 0
        
        try:
            await self._restore_active_orders()
        except Exception as e:
            sys.stderr.write(f"[CONDITIONAL] ❌ Error in _restore_active_orders: {e}\n")
            sys.stderr.flush()
            import traceback
            traceback.print_exc()
        
        sys.stderr.write("[CONDITIONAL] Entering monitoring loop with enable gate...\n")
        sys.stderr.flush()
        
        while self.is_running:
            try:
                is_enabled = self.is_enabled()
                pending_count = len(get_active_conditional_orders())
                
                if is_enabled and pending_count > 0:
                    if self._standby_mode:
                        print(f"[CONDITIONAL] ✓ Resuming active monitoring - {pending_count} pending orders")
                        self._standby_mode = False
                        await self._restore_active_orders()
                    
                    expired = expire_old_conditional_orders()
                    if expired > 0:
                        print(f"[CONDITIONAL] Expired {expired} orders")
                    
                    await asyncio.sleep(30)
                else:
                    if not self._standby_mode:
                        if not is_enabled:
                            print("[CONDITIONAL] ⏸️ Entering standby - service disabled (zero API calls)")
                        else:
                            print("[CONDITIONAL] ⏸️ Entering standby - no pending orders (zero API calls)")
                        self._standby_mode = True
                        
                        for order_id in list(self.monitor_tasks.keys()):
                            task = self.monitor_tasks.get(order_id)
                            if task and not task.done():
                                task.cancel()
                        self.monitor_tasks.clear()
                        self.monitors.clear()
                    
                    now = time.time()
                    if now - self._last_status_log > 300:
                        if is_enabled:
                            print(f"[CONDITIONAL] Standby: service enabled but no pending orders")
                        else:
                            print(f"[CONDITIONAL] Standby: service disabled")
                        self._last_status_log = now
                    
                    await asyncio.sleep(5)
                    
            except Exception as e:
                sys.stderr.write(f"[CONDITIONAL] ❌ Error in main loop: {e}\n")
                sys.stderr.flush()
                await asyncio.sleep(30)
    
    async def _restore_active_orders(self):
        """Restore monitoring for active orders after restart."""
        import sys
        sys.stderr.write("[CONDITIONAL] Checking for active orders to restore...\n")
        sys.stderr.flush()
        active_orders = get_active_conditional_orders()
        sys.stderr.write(f"[CONDITIONAL] Found {len(active_orders)} active orders\n")
        sys.stderr.flush()
        
        for order in active_orders:
            order_id = order['id']
            self.pending_orders[order_id] = order
            sys.stderr.write(f"[CONDITIONAL] Restoring monitor for order #{order_id}: {order.get('symbol')} {order.get('strike')}{order.get('opt_type')}\n")
            sys.stderr.flush()
            await self._start_monitor(order_id, order)
        
        if active_orders:
            sys.stderr.write(f"[CONDITIONAL] ✓ Restored {len(active_orders)} active orders\n")
            sys.stderr.flush()
    
    def stop(self):
        """Stop the conditional order service."""
        self.is_running = False
        
        for monitor in self.monitors.values():
            asyncio.run_coroutine_threadsafe(monitor.stop(), self._loop)
        
        self.monitors.clear()
        self.pending_orders.clear()
        
        print("[CONDITIONAL] Service stopped")
    
    def get_active_orders(self) -> List[Dict]:
        """Get all active conditional orders."""
        return get_active_conditional_orders()
    
    def get_order(self, order_id: int) -> Optional[Dict]:
        """Get a specific conditional order."""
        return get_conditional_order_by_id(order_id)


conditional_order_service = ConditionalOrderService()
