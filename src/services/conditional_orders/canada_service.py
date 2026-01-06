"""
Canada Market Conditional Order Service

Handles conditional orders for Canadian markets (TSX, CSE, NEO)
Price monitoring fallback chain: Questrade → Finnhub → yfinance
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


class CanadaConditionalOrderService(BaseConditionalOrderService):
    """
    Conditional order service for Canadian markets.
    
    Supports brokers: Questrade
    Fallback chain: Questrade → Finnhub → yfinance
    """
    
    MARKET = 'CANADA'
    
    def _init_rate_limiters(self):
        """Initialize rate limiters for Canada brokers."""
        self.rate_limiters = {
            'questrade': RateLimitTracker('questrade', 100),
            'finnhub': RateLimitTracker('finnhub', 60),
        }
    
    def get_supported_brokers(self) -> List[str]:
        """Return list of Canada market brokers."""
        return ['questrade']
    
    async def build_price_monitor(self, order: Dict, broker_instance: Any, broker_name: str) -> Optional[PriceMonitor]:
        """
        Build price monitor for Canada market orders.
        
        Fallback chain:
        1. Channel-configured broker (Questrade) - real-time
        2. Finnhub API - real-time
        3. yfinance - delayed
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
            tsym = f"{symbol}.TO" if not symbol.endswith('.TO') else symbol
            data_source = 'finnhub'
            fallback_reason = 'broker_rate_limit' if (rate_limiter and rate_limiter.should_fallback(settings_threshold)) else 'no_broker_instance'
            self._log(f"Using Finnhub for {tsym} (reason: {fallback_reason})")
            monitor = FinnhubPriceMonitor(tsym, price_callback, self.finnhub_api_key)
        
        elif YFINANCE_AVAILABLE:
            yf_symbol = f"{symbol}.TO" if not symbol.endswith('.TO') else symbol
            data_source = 'yfinance'
            self._log(f"Using yfinance for {yf_symbol} (delayed)")
            monitor = YFinancePriceMonitor(yf_symbol, price_callback)
        
        else:
            self._log(f"ERROR: No price source for {symbol}")
            return None
        
        from gui_app.database import update_conditional_order_status
        status = 'ACTIVE_MONITORING' if data_source in self.get_supported_brokers() else 'FALLBACK_MONITORING'
        update_conditional_order_status(
            order['id'],
            status,
            data_source_active=data_source
        )
        
        return monitor
