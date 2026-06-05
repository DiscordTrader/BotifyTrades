"""
Conditional Order Router

Dispatches conditional orders to market-specific services.
Manages broker registration and lifecycle across all market services.
"""

import sys
import asyncio
from typing import Dict, List, Optional, Any, Callable

from .us_service import USConditionalOrderService
from .india_service import IndiaConditionalOrderService
from .canada_service import CanadaConditionalOrderService
from .base import BaseConditionalOrderService

from gui_app.database import (
    get_conditional_order_settings,
    get_active_conditional_orders,
    get_conditional_order_by_id,
)


class ConditionalOrderRouter:
    """
    Routes conditional orders to market-specific services.
    
    Features:
    - Market detection from parsed signal
    - Isolated services per market (US, India, Canada)
    - Unified broker registration
    - Consolidated lifecycle management
    """
    
    MARKET_MAP = {
        'US': 'us',
        'USA': 'us',
        'INDIA': 'india',
        'IN': 'india',
        'CANADA': 'canada',
        'CA': 'canada',
    }
    
    BROKER_MARKET_MAP = {
        'webull': 'US',
        'webull_paper': 'US',
        'alpaca': 'US',
        'alpaca_paper': 'US',
        'tastytrade': 'US',
        'tastytrade_live': 'US',
        'tastytrade_paper': 'US',
        'ibkr': 'US',
        'ibkr_paper': 'US',
        'robinhood': 'US',
        'schwab': 'US',
        'schwab_paper': 'US',
        'upstox': 'INDIA',
        'zerodha': 'INDIA',
        'dhanq': 'INDIA',
        'questrade': 'CANADA',
        'questrade_paper': 'CANADA',
        'trading212': 'US',
        'trading212_live': 'US',
        'trading212_paper': 'US',
        'webull_official': 'US',
        'webull_official_live': 'US',
        'webull_official_paper': 'US',
    }
    
    def __init__(self):
        self.us_service = USConditionalOrderService()
        self.india_service = IndiaConditionalOrderService()
        self.canada_service = CanadaConditionalOrderService()
        
        self._services: Dict[str, BaseConditionalOrderService] = {
            'US': self.us_service,
            'INDIA': self.india_service,
            'CANADA': self.canada_service,
        }
        
        self.is_running = False
        self._bot_ref = None
        self._log("Router initialized with market-isolated services")
    
    def set_bot_ref(self, bot):
        """Store reference to bot instance for broker auto-discovery."""
        self._bot_ref = bot
        self._log(f"Bot reference registered for broker auto-discovery")
    
    def _log(self, msg: str):
        sys.stderr.write(f"[ROUTER] {msg}\n")
        sys.stderr.flush()
    
    def _get_market_from_broker(self, broker: str) -> str:
        """Determine market from broker name."""
        return self.BROKER_MARKET_MAP.get(broker.lower(), 'US')
    
    def _get_service_for_market(self, market: str) -> BaseConditionalOrderService:
        """Get the appropriate service for a market."""
        normalized = self.MARKET_MAP.get(market.upper(), 'us')
        if normalized == 'us':
            return self.us_service
        elif normalized == 'india':
            return self.india_service
        elif normalized == 'canada':
            return self.canada_service
        return self.us_service
    
    def is_enabled(self) -> bool:
        """Check if conditional order service is globally enabled."""
        settings = get_conditional_order_settings()
        return settings.get('enabled', False)
    
    def set_broker_instance(self, broker_name: str, instance: Any):
        """
        Register a broker instance with the appropriate market service.
        Automatically routes to the correct market based on broker type.
        """
        broker_lower = broker_name.lower()
        market = self._get_market_from_broker(broker_lower)
        service = self._get_service_for_market(market)
        service.set_broker_instance(broker_name, instance)
        self._log(f"Registered {broker_name} with {market} service")
    
    def set_data_hub(self, broker_key: str, hub: Any):
        """Register a streaming data hub with the appropriate market service."""
        broker_lower = broker_key.lower()
        market = self._get_market_from_broker(broker_lower)
        service = self._get_service_for_market(market)
        service.set_data_hub(broker_key, hub)
        self._log(f"Registered data hub for {broker_key} with {market} service")
    
    def set_execution_callback(self, callback: Callable, main_loop: Optional[asyncio.AbstractEventLoop] = None):
        """Set execution callback on all services."""
        for service in self._services.values():
            service.set_execution_callback(callback, main_loop)
    
    def set_notification_callback(self, callback: Callable):
        """Set notification callback on all services."""
        for service in self._services.values():
            service.set_notification_callback(callback)
    
    def start(self):
        """Start all market services."""
        if self.is_running:
            self._log("Already running")
            return
        
        self._log("Starting all market services...")
        
        for market, service in self._services.items():
            self._log(f"Starting {market} service...")
            service.start()
        
        self.is_running = True
        self._log("All market services started")
    
    def create_order(
        self,
        channel_id: str,
        parsed_signal: Dict[str, Any],
        broker: str
    ) -> Optional[int]:
        """
        Create a conditional order, routing to the appropriate market service.
        
        Market is determined from:
        1. parsed_signal['market'] if present
        2. Broker type (e.g., Upstox -> INDIA)
        3. Default: US
        """
        market = parsed_signal.get('market', '').upper()
        
        if not market:
            market = self._get_market_from_broker(broker) if broker else 'US'
        
        service = self._get_service_for_market(market)
        self._log(f"Routing order to {market} service (broker: {broker})")
        
        return service.create_order(channel_id, parsed_signal, broker)
    
    def cancel_order(self, order_id: int) -> bool:
        """Cancel an order by finding its market and delegating."""
        order = get_conditional_order_by_id(order_id)
        if not order:
            self._log(f"Order #{order_id} not found")
            return False
        
        market = order.get('market', 'US')
        service = self._get_service_for_market(market)
        return service.cancel_order(order_id)
    
    def cancel_order_by_symbol(self, channel_id: str, symbol: str) -> bool:
        """
        Cancel all pending orders for a symbol in a channel.
        
        Searches across all market services for matching orders.
        Returns True if any orders were cancelled.
        """
        cancelled_any = False
        active_orders = get_active_conditional_orders()
        
        for order in active_orders:
            if (order.get('channel_id') == channel_id and 
                order.get('symbol', '').upper() == symbol.upper() and
                order.get('status') == 'PENDING'):
                
                order_id = order.get('id')
                market = order.get('market', 'US')
                service = self._get_service_for_market(market)
                
                if service.cancel_order(order_id):
                    self._log(f"Cancelled order #{order_id} for {symbol}")
                    cancelled_any = True
        
        return cancelled_any
    
    def get_active_orders(self, market: Optional[str] = None) -> List[Dict]:
        """Get active orders, optionally filtered by market."""
        orders = get_active_conditional_orders()
        
        if market:
            market_upper = market.upper()
            orders = [o for o in orders if o.get('market', 'US') == market_upper]
        
        return orders
    
    def get_order_by_id(self, order_id: int) -> Optional[Dict]:
        """Get order by ID."""
        return get_conditional_order_by_id(order_id)
    
    def get_market_status(self) -> Dict[str, Dict]:
        """Get status of all market services."""
        status = {}
        for market, service in self._services.items():
            status[market] = {
                'running': service.is_running,
                'active_monitors': len(service.monitors),
                'pending_orders': len(service.pending_orders),
                'registered_brokers': list(service.broker_instances.keys()),
            }
        return status
    
    def shutdown(self):
        """Shutdown all market services."""
        self._log("Shutting down all market services...")
        
        for market, service in self._services.items():
            self._log(f"Shutting down {market} service...")
            service.shutdown()
        
        self.is_running = False
        self._log("All market services stopped")


conditional_order_router = ConditionalOrderRouter()
