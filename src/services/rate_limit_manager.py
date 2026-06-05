"""
Rate Limit Manager
==================
Centralized, thread-safe API rate limit tracking for all brokers.
Prevents exceeding broker API limits across all threads (Discord bot, Flask, background tasks).
"""
import threading
import time
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field
from collections import deque


@dataclass
class BrokerLimit:
    """Rate limit configuration for a broker."""
    name: str
    requests_per_window: int
    window_seconds: int
    min_interval_seconds: float
    active_interval_seconds: float
    idle_interval_seconds: float
    
    @property
    def requests_per_second(self) -> float:
        return self.requests_per_window / self.window_seconds


@dataclass 
class BrokerBucket:
    """Token bucket for tracking API usage per broker."""
    timestamps: deque = field(default_factory=deque)
    last_429_at: Optional[float] = None
    backoff_until: Optional[float] = None
    total_calls: int = 0
    rate_limit_hits: int = 0


BROKER_LIMITS: Dict[str, BrokerLimit] = {
    'webull': BrokerLimit(
        name='Webull',
        requests_per_window=30,
        window_seconds=60,
        min_interval_seconds=2.0,
        active_interval_seconds=5.0,
        idle_interval_seconds=30.0
    ),
    'alpaca': BrokerLimit(
        name='Alpaca',
        requests_per_window=200,
        window_seconds=60,
        min_interval_seconds=0.3,
        active_interval_seconds=5.0,
        idle_interval_seconds=15.0
    ),
    'robinhood': BrokerLimit(
        name='Robinhood',
        requests_per_window=8,
        window_seconds=60,
        min_interval_seconds=15.0,
        active_interval_seconds=20.0,
        idle_interval_seconds=60.0
    ),
    'ibkr': BrokerLimit(
        name='Interactive Brokers',
        requests_per_window=50,
        window_seconds=1,
        min_interval_seconds=0.02,
        active_interval_seconds=5.0,
        idle_interval_seconds=15.0
    ),
    'tastytrade': BrokerLimit(
        name='Tastytrade',
        requests_per_window=120,
        window_seconds=60,
        min_interval_seconds=0.5,
        active_interval_seconds=10.0,
        idle_interval_seconds=30.0
    ),
    'schwab': BrokerLimit(
        name='Charles Schwab',
        requests_per_window=120,
        window_seconds=60,
        min_interval_seconds=0.5,
        active_interval_seconds=5.0,
        idle_interval_seconds=15.0
    ),
    'questrade': BrokerLimit(
        name='Questrade',
        requests_per_window=20,
        window_seconds=1,
        min_interval_seconds=0.05,
        active_interval_seconds=10.0,
        idle_interval_seconds=30.0
    ),
    'zerodha': BrokerLimit(
        name='Zerodha',
        requests_per_window=10,
        window_seconds=1,
        min_interval_seconds=0.1,
        active_interval_seconds=5.0,
        idle_interval_seconds=15.0
    ),
    'upstox': BrokerLimit(
        name='Upstox',
        requests_per_window=25,
        window_seconds=1,
        min_interval_seconds=0.04,
        active_interval_seconds=5.0,
        idle_interval_seconds=15.0
    ),
    'dhanq': BrokerLimit(
        name='DhanQ',
        requests_per_window=20,
        window_seconds=1,
        min_interval_seconds=0.05,
        active_interval_seconds=8.0,
        idle_interval_seconds=20.0
    ),
    'trading212': BrokerLimit(
        name='Trading 212',
        requests_per_window=1,
        window_seconds=5,
        min_interval_seconds=5.0,
        active_interval_seconds=6.0,
        idle_interval_seconds=30.0
    ),
    'finnhub': BrokerLimit(
        name='Finnhub',
        requests_per_window=60,
        window_seconds=60,
        min_interval_seconds=1.0,
        active_interval_seconds=5.0,
        idle_interval_seconds=30.0
    ),
}


class RateLimitManager:
    """
    Centralized, thread-safe rate limit manager for all broker APIs.
    
    Features:
    - Token bucket algorithm per broker
    - Thread-safe access from Discord bot, Flask, background tasks
    - Automatic backoff on 429 errors
    - Metrics tracking for monitoring
    """
    
    _instance: Optional['RateLimitManager'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._buckets: Dict[str, BrokerBucket] = {}
        self._bucket_lock = threading.Lock()
        self._initialized = True
        
        for broker_key in BROKER_LIMITS:
            self._buckets[broker_key] = BrokerBucket()
        
        print("[RATE_LIMIT] ✓ RateLimitManager initialized with limits for all brokers")
    
    def can_make_request(self, broker: str) -> Tuple[bool, float]:
        """
        Check if a request can be made to the broker.
        
        Args:
            broker: Broker key (lowercase, e.g., 'webull', 'alpaca')
        
        Returns:
            Tuple of (can_proceed, wait_seconds)
            - If can_proceed is True, request can be made immediately
            - If can_proceed is False, wait_seconds indicates how long to wait
        """
        broker_key = broker.lower()
        
        if broker_key not in BROKER_LIMITS:
            return True, 0.0
        
        limit = BROKER_LIMITS[broker_key]
        now = time.time()
        
        with self._bucket_lock:
            bucket = self._buckets.get(broker_key)
            if bucket is None:
                bucket = BrokerBucket()
                self._buckets[broker_key] = bucket
            
            if bucket.backoff_until and now < bucket.backoff_until:
                wait_time = bucket.backoff_until - now
                return False, wait_time
            
            window_start = now - limit.window_seconds
            while bucket.timestamps and bucket.timestamps[0] < window_start:
                bucket.timestamps.popleft()
            
            if len(bucket.timestamps) >= limit.requests_per_window:
                oldest = bucket.timestamps[0]
                wait_time = (oldest + limit.window_seconds) - now + 0.1
                return False, max(wait_time, limit.min_interval_seconds)
            
            return True, 0.0
    
    def record_request(self, broker: str) -> None:
        """Record that a request was made to the broker."""
        broker_key = broker.lower()
        
        if broker_key not in BROKER_LIMITS:
            return
        
        now = time.time()
        
        with self._bucket_lock:
            bucket = self._buckets.get(broker_key)
            if bucket is None:
                bucket = BrokerBucket()
                self._buckets[broker_key] = bucket
            
            bucket.timestamps.append(now)
            bucket.total_calls += 1
    
    def record_rate_limit_hit(self, broker: str, backoff_seconds: float = 60.0) -> None:
        """
        Record a 429 rate limit response from the broker.
        
        Args:
            broker: Broker key
            backoff_seconds: How long to back off (default 60s)
        """
        broker_key = broker.lower()
        now = time.time()
        
        with self._bucket_lock:
            bucket = self._buckets.get(broker_key)
            if bucket is None:
                bucket = BrokerBucket()
                self._buckets[broker_key] = bucket
            
            bucket.last_429_at = now
            bucket.backoff_until = now + backoff_seconds
            bucket.rate_limit_hits += 1
            
            print(f"[RATE_LIMIT] ⚠️ {broker} rate limit hit - backing off for {backoff_seconds}s")
    
    def get_recommended_interval(self, broker: str, is_active: bool = True) -> float:
        """
        Get the recommended polling interval for a broker.
        
        Args:
            broker: Broker key
            is_active: Whether actively monitoring positions (True) or idle (False)
        
        Returns:
            Recommended interval in seconds
        """
        broker_key = broker.lower()
        
        if broker_key not in BROKER_LIMITS:
            return 30.0
        
        limit = BROKER_LIMITS[broker_key]
        
        if is_active:
            return limit.active_interval_seconds
        else:
            return limit.idle_interval_seconds
    
    def get_status(self, broker: str) -> Dict:
        """Get current rate limit status for a broker."""
        broker_key = broker.lower()
        now = time.time()
        
        if broker_key not in BROKER_LIMITS:
            return {'available': True, 'error': 'Unknown broker'}
        
        limit = BROKER_LIMITS[broker_key]
        
        with self._bucket_lock:
            bucket = self._buckets.get(broker_key, BrokerBucket())
            
            window_start = now - limit.window_seconds
            recent_count = sum(1 for ts in bucket.timestamps if ts >= window_start)
            
            is_backing_off = bucket.backoff_until and now < bucket.backoff_until
            backoff_remaining = max(0, (bucket.backoff_until or 0) - now)
            
            return {
                'broker': limit.name,
                'requests_in_window': recent_count,
                'window_limit': limit.requests_per_window,
                'window_seconds': limit.window_seconds,
                'utilization_pct': (recent_count / limit.requests_per_window) * 100,
                'is_backing_off': is_backing_off,
                'backoff_remaining': backoff_remaining,
                'total_calls': bucket.total_calls,
                'rate_limit_hits': bucket.rate_limit_hits,
                'recommended_active_interval': limit.active_interval_seconds,
                'recommended_idle_interval': limit.idle_interval_seconds,
            }
    
    def get_all_status(self) -> Dict[str, Dict]:
        """Get rate limit status for all brokers."""
        return {broker: self.get_status(broker) for broker in BROKER_LIMITS}
    
    def reset_broker(self, broker: str) -> None:
        """Reset rate limit tracking for a broker."""
        broker_key = broker.lower()
        
        with self._bucket_lock:
            if broker_key in self._buckets:
                self._buckets[broker_key] = BrokerBucket()
                print(f"[RATE_LIMIT] ✓ Reset rate limit tracking for {broker}")


rate_limit_manager = RateLimitManager()


def get_rate_limit_manager() -> RateLimitManager:
    """Get the singleton RateLimitManager instance."""
    return rate_limit_manager
