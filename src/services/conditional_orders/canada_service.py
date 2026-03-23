"""
Canada Market Conditional Order Service

Handles conditional orders for Canadian markets (TSX, CSE, NEO)
Price monitoring fallback chain: Questrade → Cross-Broker Hub → Broker REST API
"""

import sys
from typing import Dict, List, Optional, Any

from .base import (
    BaseConditionalOrderService,
    PriceMonitor,
    BrokerPriceMonitor,
    RateLimitTracker,
)


class CanadaConditionalOrderService(BaseConditionalOrderService):
    """
    Conditional order service for Canadian markets.
    
    Supports brokers: Questrade
    Fallback chain: Questrade → Cross-Broker Hub → Broker REST API
    """
    
    MARKET = 'CANADA'
    
    def _init_rate_limiters(self):
        """Initialize rate limiters for Canada brokers."""
        self.rate_limiters = {
            'questrade': RateLimitTracker('questrade', 100),
        }
    
    def get_supported_brokers(self) -> List[str]:
        """Return list of Canada market brokers."""
        return ['questrade']
    
    async def build_price_monitor(self, order: Dict, broker_instance: Any, broker_name: str) -> Optional[PriceMonitor]:
        """
        Build price monitor for Canada market orders.
        
        Fallback chain:
        1. Channel-configured broker (Questrade) - real-time REST
        2. Any connected broker REST API (cross-broker fallback)
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
            self._log(f"Using {broker_name} for {symbol} (real-time REST, cross-broker hub fallback)")
            monitor = BrokerPriceMonitor(symbol, price_callback, broker_name, broker_instance)

        elif broker_instance:
            data_source = broker_name.lower()
            self._log(f"Using {broker_name} for {symbol} (broker REST with cross-hub fallback)")
            monitor = BrokerPriceMonitor(symbol, price_callback, broker_name, broker_instance)

        else:
            any_broker_name = None
            any_broker_inst = None
            for bname, binst in self.broker_instances.items():
                if binst and hasattr(binst, 'get_quote'):
                    any_broker_name = bname
                    any_broker_inst = binst
                    break
            if any_broker_inst:
                data_source = any_broker_name.lower()
                self._log(f"Using {any_broker_name} for {symbol} (fallback broker REST)")
                monitor = BrokerPriceMonitor(symbol, price_callback, any_broker_name, any_broker_inst)
            else:
                self._log(f"ERROR: No price source for {symbol} — no brokers connected")
                return None
        
        from gui_app.database import update_conditional_order_status
        status = 'ACTIVE_MONITORING' if data_source in self.get_supported_brokers() else 'FALLBACK_MONITORING'
        update_conditional_order_status(
            order['id'],
            status,
            data_source_active=data_source
        )
        
        return monitor
