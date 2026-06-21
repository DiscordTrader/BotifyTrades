"""
US Market Conditional Order Service

Handles conditional orders for US markets (NYSE, NASDAQ, etc.)
Price monitoring chain: UPH (all hubs) → Streaming Hub → Cross-Broker Hub → Broker REST API
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
            'webull_official': RateLimitTracker('webull_official', 120),
            'alpaca': RateLimitTracker('alpaca', 200),
            'tastytrade': RateLimitTracker('tastytrade', 60),
            'ibkr': RateLimitTracker('ibkr', 100),
            'robinhood': RateLimitTracker('robinhood', 60),
            'schwab': RateLimitTracker('schwab', 60),
            'trading212': RateLimitTracker('trading212', 30),
        }
    
    def get_supported_brokers(self) -> List[str]:
        """Return list of US market brokers."""
        return ['webull', 'webull_official', 'alpaca', 'tastytrade', 'ibkr', 'robinhood', 'schwab', 'trading212']
    
    async def build_price_monitor(self, order: Dict, broker_instance: Any, broker_name: str) -> Optional[PriceMonitor]:
        """
        Build price monitor for US market orders.
        
        Priority chain (strict):
        1. Order's broker streaming hub (WebSocket/MQTT active) — sub-100ms, zero API calls
        2. Alt broker streaming hub (Schwab/Webull cross-broker WebSocket active)
        3. Order's broker REST API — real-time polling via assigned broker
        4. Order's broker hub (not yet streaming, will auto-upgrade)
        5. Alt broker hub (not yet streaming, will auto-upgrade)
        6. Any connected broker REST API (last resort)
        """
        symbol = order['symbol']

        broker_lower = broker_name.lower() if broker_name else ''
        broker_key = broker_lower.replace('_paper', '').replace('_live', '')

        data_source = None
        monitor = None

        async def price_callback(sym: str, price: float):
            await self._on_price_update(order['id'], sym, price)

        # P0: UPH — unified hub aggregating ALL broker price sources.
        # Required when multiple brokers monitor the same symbol: using a single
        # price source ensures all conditional orders see the same price and trigger
        # at the same level, preventing one broker from firing while another doesn't
        # due to REST feed divergence (e.g. Schwab REST vs IBKR REST differing by cents).
        # StreamingPriceMonitor degrades gracefully when UPH has no cached data for a
        # symbol — it falls through to _try_any_streaming_hub() then REST polling.
        try:
            from src.services.unified_price_hub import get_unified_price_hub
            _uph = get_unified_price_hub()
            if _uph and _uph._poll_running:
                data_source = 'uph_stream' if _uph.is_streaming() else 'uph_rest'
                self._log(f"[P0] UPH for {symbol} ({'streaming' if _uph.is_streaming() else 'REST-poll'} — unified price source)")
                # _try_subscribe_streaming() needs a broker_instance to subscribe the symbol
                # so ticks flow into UPH. Prefer the order's own broker.
                # Fallback order: MQTT/WebSocket client (Webull/Schwab), then IBKR (ib_insync).
                _sub_broker = broker_instance
                if _sub_broker is None:
                    for _bn, _bi in self.broker_instances.items():
                        if _bi and hasattr(_bi, '_streaming_client') and _bi._streaming_client is not None:
                            _sub_broker = _bi
                            self._log(f"[P0] Using {_bn} streaming client for {symbol} subscription")
                            break
                    if _sub_broker is None:
                        # IBKR has no _streaming_client — uses ib_insync directly via IBKRDataHub
                        for _bn, _bi in self.broker_instances.items():
                            if _bi and hasattr(_bi, 'ib') and getattr(_bi, 'connected', False):
                                _sub_broker = _bi
                                self._log(f"[P0] Using {_bn} IBKR hub for {symbol} subscription")
                                break
                monitor = StreamingPriceMonitor(
                    symbol, price_callback, _uph, 'uph',
                    broker_instance=_sub_broker,
                    alt_broker_instances=self.broker_instances,
                )
        except Exception as _uph_ex:
            self._log(f"[P0] UPH unavailable for {symbol}: {_uph_ex}")

        if monitor:
            if hasattr(monitor, 'order_id'):
                monitor.order_id = order['id']
            from gui_app.database import update_conditional_order_status
            update_conditional_order_status(order['id'], 'ACTIVE_MONITORING', data_source_active=data_source)
            return monitor

        hub = self.get_data_hub(broker_name) if broker_name else None
        hub_is_streaming = self.is_hub_streaming(broker_name) if broker_name else False
        
        alt_hub = None
        alt_hub_name = None
        alt_hub_streaming = False
        alt_hub_broker = None
        alt_hub_can_stream = False
        for alt_key in ['webull', 'webull_official', 'schwab', 'ibkr', 'tastytrade', 'trading212']:
            if alt_key == broker_key:
                continue
            alt = self.get_data_hub(alt_key)
            if alt and alt is not hub:
                alt_streaming = self.is_hub_streaming(alt_key)
                alt_has_streaming = hasattr(alt, 'is_streaming')
                if alt_hub is None or (alt_streaming and not alt_hub_streaming) or (alt_has_streaming and not alt_hub_can_stream and not alt_hub_streaming):
                    alt_hub = alt
                    alt_hub_name = alt_key
                    alt_hub_streaming = alt_streaming
                    alt_hub_can_stream = alt_has_streaming
                    alt_hub_broker = self.broker_instances.get(alt_key)
                if alt_hub_streaming:
                    break
        
        is_t212 = broker_key == 'trading212'
        is_cross_broker = alt_hub is not None and alt_hub_name != broker_key
        alt_brokers = self.broker_instances if (is_t212 or is_cross_broker) else {}

        if hub and hub_is_streaming:
            data_source = f"{broker_key}_stream"
            self._log(f"[P1] STREAMING hub for {symbol} via {broker_name} (sub-100ms)")
            monitor = StreamingPriceMonitor(
                symbol, price_callback, hub, broker_name,
                broker_instance=broker_instance,
                alt_broker_instances=alt_brokers
            )
        
        elif alt_hub and alt_hub_streaming:
            data_source = f"{alt_hub_name}_stream"
            self._log(f"[P2] Alt STREAMING hub for {symbol} via {alt_hub_name} (cross-broker WebSocket, order broker={broker_name})")
            monitor = StreamingPriceMonitor(
                symbol, price_callback, alt_hub, alt_hub_name,
                broker_instance=alt_hub_broker,
                alt_broker_instances=alt_brokers,
                order_broker=broker_name
            )
        
        elif broker_instance and broker_key != 'trading212':
            data_source = broker_name.lower()
            self._log(f"[P3] REST API for {symbol} via {broker_name}")
            monitor = BrokerPriceMonitor(symbol, price_callback, broker_name, broker_instance, alt_broker_instances=self.broker_instances)
        
        elif hub and hasattr(hub, 'is_streaming'):
            data_source = f"{broker_key}_stream"
            self._log(f"[P4] Hub (pending stream) for {symbol} via {broker_name} (will auto-upgrade)")
            monitor = StreamingPriceMonitor(
                symbol, price_callback, hub, broker_name,
                broker_instance=broker_instance,
                alt_broker_instances=alt_brokers
            )
        
        elif alt_hub:
            data_source = f"{alt_hub_name}_stream"
            self._log(f"[P5] Alt hub for {symbol} via {alt_hub_name} (order broker={broker_name})")
            monitor = StreamingPriceMonitor(
                symbol, price_callback, alt_hub, alt_hub_name,
                broker_instance=alt_hub_broker,
                alt_broker_instances=alt_brokers,
                order_broker=broker_name
            )
        
        elif hub:
            data_source = f"{broker_key}_rest"
            self._log(f"[P5b] REST-only hub for {symbol} via {broker_name} (no streaming capability)")
            monitor = StreamingPriceMonitor(
                symbol, price_callback, hub, broker_name,
                broker_instance=broker_instance,
                alt_broker_instances=alt_brokers
            )
        
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
                self._log(f"[P6] Fallback REST for {symbol} via {any_broker_name} (no primary broker)")
                monitor = BrokerPriceMonitor(symbol, price_callback, any_broker_name, any_broker_inst, alt_broker_instances=alt_brokers)
            else:
                self._log(f"ERROR: No price source for {symbol} — no brokers or hubs available")
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
