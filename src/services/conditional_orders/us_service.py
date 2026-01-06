"""
US Market Conditional Order Service

Handles conditional orders for US markets (NYSE, NASDAQ, etc.)
Price monitoring fallback chain: Webull/Alpaca → Finnhub → yfinance
"""

import sys
from typing import Dict, List, Optional, Any

from .base import (
    BaseConditionalOrderService,
    PriceMonitor,
    BrokerPriceMonitor,
    FinnhubPriceMonitor,
    YFinancePriceMonitor,
    RateLimitTracker,
    YFINANCE_AVAILABLE,
)


class USConditionalOrderService(BaseConditionalOrderService):
    """
    Conditional order service for US markets.
    
    Supports brokers: Webull, Alpaca, Tastytrade, IBKR, Robinhood, Schwab
    Fallback chain: Channel Broker → Finnhub → yfinance
    """
    
    MARKET = 'US'
    
    def _init_rate_limiters(self):
        """Initialize rate limiters for US brokers."""
        self.rate_limiters = {
            'webull': RateLimitTracker('webull', 120),
            'alpaca': RateLimitTracker('alpaca', 200),
            'tastytrade': RateLimitTracker('tastytrade', 60),
            'ibkr': RateLimitTracker('ibkr', 100),
            'robinhood': RateLimitTracker('robinhood', 60),
            'schwab': RateLimitTracker('schwab', 60),
            'finnhub': RateLimitTracker('finnhub', 60),
        }
    
    def get_supported_brokers(self) -> List[str]:
        """Return list of US market brokers."""
        return ['webull', 'alpaca', 'tastytrade', 'ibkr', 'robinhood', 'schwab']
    
    async def build_price_monitor(self, order: Dict, broker_instance: Any, broker_name: str) -> Optional[PriceMonitor]:
        """
        Build price monitor for US market orders.
        
        Fallback chain:
        1. Channel-configured broker (Webull/Alpaca/etc.) - real-time
        2. Finnhub API - real-time
        3. yfinance - delayed (~15 min)
        """
        symbol = order['symbol']
        settings_threshold = 0.8
        
        rate_limiter = self.rate_limiters.get(broker_name.lower()) if broker_name else None
        broker_rate_ok = rate_limiter and not rate_limiter.should_fallback(settings_threshold)
        
        data_source = None
        monitor = None
        
        async def price_callback(sym: str, price: float):
            await self._on_price_update(order['id'], sym, price)
        
        if broker_instance and broker_rate_ok:
            data_source = broker_name.lower()
            self._log(f"Using {broker_name} for {symbol} (real-time)")
            monitor = BrokerPriceMonitor(symbol, price_callback, broker_name, broker_instance)
        
        elif self.finnhub_api_key:
            data_source = 'finnhub'
            fallback_reason = 'broker_rate_limit' if (rate_limiter and rate_limiter.should_fallback(settings_threshold)) else 'no_broker_instance'
            self._log(f"Using Finnhub for {symbol} (reason: {fallback_reason})")
            monitor = FinnhubPriceMonitor(symbol, price_callback, self.finnhub_api_key)
        
        elif YFINANCE_AVAILABLE:
            data_source = 'yfinance'
            self._log(f"Using yfinance for {symbol} (delayed ~15min)")
            monitor = YFinancePriceMonitor(symbol, price_callback)
        
        else:
            self._log(f"ERROR: No price source for {symbol}")
            self._log(f"  - Set FINNHUB_API_KEY for real-time data")
            self._log(f"  - Or install yfinance: pip install yfinance")
            return None
        
        from gui_app.database import update_conditional_order_status
        status = 'ACTIVE_MONITORING' if data_source in self.get_supported_brokers() else 'FALLBACK_MONITORING'
        update_conditional_order_status(
            order['id'],
            status,
            data_source_active=data_source
        )
        
        return monitor
