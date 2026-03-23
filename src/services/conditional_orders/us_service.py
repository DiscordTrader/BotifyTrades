"""
US Market Conditional Order Service

Handles conditional orders for US markets (NYSE, NASDAQ, etc.)
Price monitoring fallback chain: Streaming Hub → Cross-Broker Hub → Broker REST API
"""

import sys
from typing import Dict, List, Optional, Any

from .base import (
    BaseConditionalOrderService,
    PriceMonitor,
    StreamingPriceMonitor,
    BrokerPriceMonitor,
    RateLimitTracker,
)


class USConditionalOrderService(BaseConditionalOrderService):
    """
    Conditional order service for US markets.
    
    Supports brokers: Webull, Alpaca, Tastytrade, IBKR, Robinhood, Schwab
    Fallback chain: Channel Broker → Cross-Broker Hub → Any Connected Broker REST
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
            'trading212': RateLimitTracker('trading212', 30),
        }
    
    def get_supported_brokers(self) -> List[str]:
        """Return list of US market brokers."""
        return ['webull', 'alpaca', 'tastytrade', 'ibkr', 'robinhood', 'schwab', 'trading212']
    
    async def build_price_monitor(self, order: Dict, broker_instance: Any, broker_name: str) -> Optional[PriceMonitor]:
        """
        Build price monitor for US market orders.
        
        Priority chain:
        1. Data hub with active streaming (WebSocket/MQTT) - sub-100ms, zero API calls
        2. Data hub without streaming (hub cache + broker REST fallback) - broker-first
        3. Alt streaming hub (Schwab/Webull cross-broker WebSocket) - for brokers without own hub
        4. Alt hub without streaming (cross-broker cache)
        5. Broker REST API direct (incl. T212 portfolio quotes) - real-time polling
        6. Any connected broker REST API
        7. Cross-broker hub fallback (via BrokerPriceMonitor._try_any_streaming_hub)
        """
        symbol = order['symbol']
        settings_threshold = 0.8
        
        broker_lower = broker_name.lower() if broker_name else ''
        broker_key = broker_lower.replace('_paper', '').replace('_live', '')
        rate_limiter = self.rate_limiters.get(broker_key) if broker_key else None
        if not rate_limiter and broker_lower:
            rate_limiter = self.rate_limiters.get(broker_lower)
        broker_rate_ok = rate_limiter and not rate_limiter.should_fallback(settings_threshold)
        
        data_source = None
        monitor = None
        
        async def price_callback(sym: str, price: float):
            await self._on_price_update(order['id'], sym, price)
        
        hub = self.get_data_hub(broker_name) if broker_name else None
        hub_is_streaming = self.is_hub_streaming(broker_name) if broker_name else False
        
        alt_hub = None
        alt_hub_name = None
        alt_hub_streaming = False
        alt_hub_broker = None
        if not hub:
            for alt_key in ['schwab', 'webull']:
                alt = self.get_data_hub(alt_key)
                if alt:
                    alt_hub = alt
                    alt_hub_name = alt_key
                    alt_hub_streaming = self.is_hub_streaming(alt_key)
                    alt_hub_broker = self.broker_instances.get(alt_key)
                    if alt_hub_streaming:
                        break
        
        if hub and hub_is_streaming:
            data_source = f"{broker_key}_stream"
            self._log(f"Using STREAMING hub for {symbol} via {broker_name} (sub-100ms, zero API calls)")
            monitor = StreamingPriceMonitor(
                symbol, price_callback, hub, broker_name,
                broker_instance=broker_instance
            )
        
        elif hub:
            data_source = f"{broker_key}_stream"
            self._log(f"Using data hub for {symbol} via {broker_name} (hub cache + streaming subscription, will auto-upgrade when streaming connects)")
            monitor = StreamingPriceMonitor(
                symbol, price_callback, hub, broker_name,
                broker_instance=broker_instance
            )
        
        elif alt_hub and alt_hub_streaming:
            data_source = f"{alt_hub_name}_stream"
            self._log(f"Using STREAMING hub for {symbol} via {alt_hub_name} (cross-broker WebSocket for {broker_name})")
            monitor = StreamingPriceMonitor(
                symbol, price_callback, alt_hub, alt_hub_name,
                broker_instance=alt_hub_broker
            )
        
        elif alt_hub:
            data_source = f"{alt_hub_name}_stream"
            self._log(f"Using data hub for {symbol} via {alt_hub_name} (cross-broker hub + streaming subscription for {broker_name})")
            monitor = StreamingPriceMonitor(
                symbol, price_callback, alt_hub, alt_hub_name,
                broker_instance=alt_hub_broker
            )
        
        elif broker_instance and broker_rate_ok:
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
                self._log(f"Using {any_broker_name} for {symbol} (fallback broker REST, no primary broker)")
                monitor = BrokerPriceMonitor(symbol, price_callback, any_broker_name, any_broker_inst)
            else:
                self._log(f"ERROR: No price source for {symbol} — no brokers connected and no streaming hubs available")
                return None
        
        if monitor and hasattr(monitor, 'order_id'):
            monitor.order_id = order['id']

        from gui_app.database import update_conditional_order_status
        is_streaming = data_source and data_source.endswith('_stream')
        status = 'ACTIVE_MONITORING' if (is_streaming or data_source in self.get_supported_brokers()) else 'FALLBACK_MONITORING'
        update_conditional_order_status(
            order['id'],
            status,
            data_source_active=data_source
        )

        if broker_key == 'trading212' and monitor:
            try:
                from src.services.trading212_data_hub import get_trading212_data_hub
                t212_hub = get_trading212_data_hub()
                if t212_hub:
                    t212_hub.add_conditional_symbol(symbol)
            except Exception:
                pass

        return monitor
