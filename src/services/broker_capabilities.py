"""
Broker Capabilities Map
=======================
Defines which price quote APIs each broker supports for stocks and options.

Used by PriceMonitorService for broker-aware price fetching with dynamic fallback.
"""
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum


class AssetType(Enum):
    """Types of assets for price quotes."""
    STOCK = "stock"
    OPTION = "option"


@dataclass
class BrokerCapability:
    """Capability definition for a broker."""
    broker_id: str
    supports_stock_quotes: bool
    supports_option_quotes: bool
    rate_limit_key: str
    priority: int = 50


BROKER_CAPABILITIES: Dict[str, BrokerCapability] = {
    'WEBULL': BrokerCapability(
        broker_id='WEBULL',
        supports_stock_quotes=True,
        supports_option_quotes=False,
        rate_limit_key='webull',
        priority=40
    ),
    'ALPACA': BrokerCapability(
        broker_id='ALPACA',
        supports_stock_quotes=True,
        supports_option_quotes=True,
        rate_limit_key='alpaca',
        priority=30
    ),
    'ALPACA_PAPER': BrokerCapability(
        broker_id='ALPACA_PAPER',
        supports_stock_quotes=True,
        supports_option_quotes=True,
        rate_limit_key='alpaca',
        priority=31
    ),
    'SCHWAB': BrokerCapability(
        broker_id='SCHWAB',
        supports_stock_quotes=True,
        supports_option_quotes=True,
        rate_limit_key='schwab',
        priority=20
    ),
    'IBKR': BrokerCapability(
        broker_id='IBKR',
        supports_stock_quotes=True,
        supports_option_quotes=True,
        rate_limit_key='ibkr',
        priority=25
    ),
    'ROBINHOOD': BrokerCapability(
        broker_id='ROBINHOOD',
        supports_stock_quotes=True,
        supports_option_quotes=True,
        rate_limit_key='robinhood',
        priority=35
    ),
    'TASTYTRADE': BrokerCapability(
        broker_id='TASTYTRADE',
        supports_stock_quotes=False,
        supports_option_quotes=True,
        rate_limit_key='tastytrade',
        priority=45
    ),
    'QUESTRADE': BrokerCapability(
        broker_id='QUESTRADE',
        supports_stock_quotes=True,
        supports_option_quotes=True,
        rate_limit_key='questrade',
        priority=50
    ),
    'UPSTOX': BrokerCapability(
        broker_id='UPSTOX',
        supports_stock_quotes=True,
        supports_option_quotes=True,
        rate_limit_key='upstox',
        priority=55
    ),
    'ZERODHA': BrokerCapability(
        broker_id='ZERODHA',
        supports_stock_quotes=True,
        supports_option_quotes=True,
        rate_limit_key='zerodha',
        priority=56
    ),
    'TRADING212': BrokerCapability(
        broker_id='TRADING212',
        supports_stock_quotes=False,
        supports_option_quotes=False,
        rate_limit_key='trading212',
        priority=52
    ),
    'DHAN': BrokerCapability(
        broker_id='DHAN',
        supports_stock_quotes=True,
        supports_option_quotes=True,
        rate_limit_key='dhan',
        priority=57
    ),
}


def get_broker_capability(broker_id: str) -> Optional[BrokerCapability]:
    """Get capability for a specific broker."""
    normalized = broker_id.upper().replace('-', '_').replace(' ', '_')
    return BROKER_CAPABILITIES.get(normalized)


def can_fetch_quotes(broker_id: str, asset_type: AssetType) -> bool:
    """Check if a broker can fetch quotes for the given asset type."""
    cap = get_broker_capability(broker_id)
    if not cap:
        return False
    
    if asset_type == AssetType.STOCK:
        return cap.supports_stock_quotes
    elif asset_type == AssetType.OPTION:
        return cap.supports_option_quotes
    return False


def get_fallback_brokers(
    position_broker_id: str,
    connected_broker_ids: List[str],
    asset_type: AssetType
) -> List[str]:
    """
    Build a prioritized fallback list for price fetching.
    
    Priority order:
    1. Position's connected broker (if capable)
    2. Other connected brokers (sorted by priority, if capable)
    3. External data sources (Finnhub, yfinance) handled separately
    
    Args:
        position_broker_id: The broker ID for this position's channel
        connected_broker_ids: All brokers currently connected
        asset_type: Stock or option
        
    Returns:
        Ordered list of broker IDs to try for price fetching
    """
    fallback_list = []
    
    if can_fetch_quotes(position_broker_id, asset_type):
        fallback_list.append(position_broker_id)
    
    other_brokers = []
    for broker_id in connected_broker_ids:
        if broker_id == position_broker_id:
            continue
        if can_fetch_quotes(broker_id, asset_type):
            cap = get_broker_capability(broker_id)
            if cap:
                other_brokers.append((broker_id, cap.priority))
    
    other_brokers.sort(key=lambda x: x[1])
    
    for broker_id, _ in other_brokers:
        if broker_id not in fallback_list:
            fallback_list.append(broker_id)
    
    return fallback_list


def get_rate_limit_key(broker_id: str) -> str:
    """Get the rate limit key for a broker."""
    cap = get_broker_capability(broker_id)
    if cap:
        return cap.rate_limit_key
    return broker_id.lower().replace('_', '')
