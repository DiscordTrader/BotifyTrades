"""
Broker Adapters - Standardized timestamp and fill data extraction for all supported brokers

Each broker returns order/fill data in different formats. This module provides
unified adapters to extract:
- Fill timestamps
- Fill prices
- Order IDs
- Partial fill handling
"""

from datetime import datetime
from typing import Dict, Optional, Any
from dataclasses import dataclass


@dataclass
class BrokerFillData:
    broker: str
    order_id: str
    symbol: str
    asset_type: str
    side: str
    quantity: int
    fill_price: float
    filled_at: datetime
    strike: Optional[float] = None
    expiry: Optional[str] = None
    call_put: Optional[str] = None
    is_partial: bool = False
    total_qty: Optional[int] = None
    fees: float = 0.0
    raw_data: Optional[Dict] = None


class BaseBrokerAdapter:
    BROKER_NAME = 'base'
    HAS_PRECISE_FILL_TIME = True
    
    def parse_fill(self, raw_order: Dict) -> Optional[BrokerFillData]:
        raise NotImplementedError
    
    def normalize_timestamp(self, timestamp: Any) -> Optional[datetime]:
        if timestamp is None:
            return None
        if isinstance(timestamp, datetime):
            return timestamp
        if isinstance(timestamp, str):
            for fmt in [
                '%Y-%m-%dT%H:%M:%S.%fZ',
                '%Y-%m-%dT%H:%M:%SZ',
                '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%d %H:%M:%S',
                '%m/%d/%Y %H:%M:%S',
            ]:
                try:
                    return datetime.strptime(timestamp.replace(' EST', '').replace(' EDT', ''), fmt)
                except ValueError:
                    continue
            try:
                return datetime.fromisoformat(timestamp.replace('Z', '+00:00').replace(' EST', '').replace(' EDT', ''))
            except:
                pass
        return None


class WebullAdapter(BaseBrokerAdapter):
    BROKER_NAME = 'webull'
    HAS_PRECISE_FILL_TIME = True
    
    def parse_fill(self, raw_order: Dict) -> Optional[BrokerFillData]:
        try:
            filled_at = self.normalize_timestamp(
                raw_order.get('filledTime') or raw_order.get('createTime')
            )
            if not filled_at:
                filled_at = datetime.now()
            
            symbol = raw_order.get('ticker', {}).get('symbol', '') or raw_order.get('symbol', '')
            
            return BrokerFillData(
                broker=self.BROKER_NAME,
                order_id=str(raw_order.get('orderId', '')),
                symbol=symbol,
                asset_type='option' if raw_order.get('assetType') == 'OPTION' else 'stock',
                side=raw_order.get('action', 'BUY'),
                quantity=int(raw_order.get('filledQuantity', 0) or raw_order.get('totalQuantity', 0)),
                fill_price=float(raw_order.get('avgFilledPrice', 0) or raw_order.get('lmtPrice', 0)),
                filled_at=filled_at,
                strike=raw_order.get('optionStrike'),
                expiry=raw_order.get('optionExpireDate'),
                call_put=raw_order.get('optionType'),
                is_partial=raw_order.get('filledQuantity', 0) < raw_order.get('totalQuantity', 0),
                fees=float(raw_order.get('totalCost', 0)) - float(raw_order.get('filledValue', 0)),
                raw_data=raw_order
            )
        except Exception as e:
            print(f"[ADAPTER] Webull parse error: {e}")
            return None


class AlpacaAdapter(BaseBrokerAdapter):
    BROKER_NAME = 'alpaca'
    HAS_PRECISE_FILL_TIME = True
    
    def parse_fill(self, raw_order: Dict) -> Optional[BrokerFillData]:
        try:
            filled_at = self.normalize_timestamp(raw_order.get('filled_at'))
            if not filled_at:
                filled_at = self.normalize_timestamp(raw_order.get('submitted_at')) or datetime.now()
            
            return BrokerFillData(
                broker=self.BROKER_NAME,
                order_id=str(raw_order.get('id', '')),
                symbol=raw_order.get('symbol', ''),
                asset_type='option' if raw_order.get('asset_class') == 'option' else 'stock',
                side=raw_order.get('side', 'buy').upper(),
                quantity=int(raw_order.get('filled_qty', 0)),
                fill_price=float(raw_order.get('filled_avg_price', 0)),
                filled_at=filled_at,
                is_partial=int(raw_order.get('filled_qty', 0)) < int(raw_order.get('qty', 0)),
                raw_data=raw_order
            )
        except Exception as e:
            print(f"[ADAPTER] Alpaca parse error: {e}")
            return None


class TastytradeAdapter(BaseBrokerAdapter):
    BROKER_NAME = 'tastytrade'
    HAS_PRECISE_FILL_TIME = True
    
    def parse_fill(self, raw_order: Dict) -> Optional[BrokerFillData]:
        try:
            filled_at = self.normalize_timestamp(
                raw_order.get('filled_time') or raw_order.get('terminal_at') or
                raw_order.get('received_at') or raw_order.get('received-at') or
                raw_order.get('updated-at')
            )
            if not filled_at:
                filled_at = datetime.now()
            
            symbol = raw_order.get('symbol', '') or raw_order.get('underlying_symbol', '') or raw_order.get('underlying-symbol', '')
            asset_type = raw_order.get('asset_type', 'stock')
            if asset_type == 'stock' and raw_order.get('order-type') == 'Option':
                asset_type = 'option'
            
            side = raw_order.get('action', 'BUY')
            
            return BrokerFillData(
                broker=self.BROKER_NAME,
                order_id=str(raw_order.get('order_id', '') or raw_order.get('id', '')),
                symbol=symbol,
                asset_type=asset_type,
                side=side,
                quantity=int(float(raw_order.get('quantity', 0) or 0)),
                fill_price=float(raw_order.get('filled_price', 0) or raw_order.get('fill_price', 0) or raw_order.get('price', 0) or 0),
                filled_at=filled_at,
                raw_data=raw_order,
                strike=raw_order.get('strike'),
                expiry=raw_order.get('expiry'),
                call_put=raw_order.get('direction')
            )
        except Exception as e:
            print(f"[ADAPTER] Tastytrade parse error: {e}")
            return None


class SchwabAdapter(BaseBrokerAdapter):
    BROKER_NAME = 'schwab'
    HAS_PRECISE_FILL_TIME = False
    
    def parse_fill(self, raw_order: Dict) -> Optional[BrokerFillData]:
        try:
            symbol = raw_order.get('symbol', '')
            asset_type = 'stock'
            instruction = raw_order.get('instruction', 'BUY')
            
            legs = raw_order.get('orderLegCollection', [])
            if legs:
                leg = legs[0]
                inst = leg.get('instrument', {})
                asset_type = 'option' if inst.get('assetType', '').upper() == 'OPTION' else 'stock'
                symbol = inst.get('symbol', symbol)
                instruction = leg.get('instruction', instruction)
            
            total_qty = 0
            total_cost = 0.0
            latest_time = None
            
            activities = raw_order.get('orderActivityCollection', [])
            for activity in activities:
                for leg_data in activity.get('executionLegs', []):
                    leg_qty = int(leg_data.get('quantity', 0))
                    leg_price = float(leg_data.get('price', 0))
                    total_qty += leg_qty
                    total_cost += leg_qty * leg_price
                    leg_time = self.normalize_timestamp(leg_data.get('time'))
                    if leg_time and (latest_time is None or leg_time > latest_time):
                        latest_time = leg_time
            
            if total_qty == 0:
                total_qty = int(raw_order.get('filledQuantity', 0))
                total_cost = total_qty * float(raw_order.get('price', 0))
            
            avg_price = total_cost / total_qty if total_qty > 0 else float(raw_order.get('price', 0))
            
            filled_at = latest_time or self.normalize_timestamp(raw_order.get('closeTime') or raw_order.get('enteredTime'))
            if not filled_at:
                filled_at = datetime.now()
            
            side_map = {
                'BUY': 'BUY', 'SELL': 'SELL',
                'BUY_TO_OPEN': 'BTO', 'SELL_TO_CLOSE': 'STC',
                'BUY_TO_CLOSE': 'BTC', 'SELL_TO_OPEN': 'STO',
            }
            normalized_side = side_map.get(instruction.upper(), instruction)
            
            return BrokerFillData(
                broker=self.BROKER_NAME,
                order_id=str(raw_order.get('orderId', '')),
                symbol=symbol,
                asset_type=asset_type,
                side=normalized_side,
                quantity=total_qty,
                fill_price=avg_price,
                filled_at=filled_at,
                raw_data=raw_order
            )
        except Exception as e:
            print(f"[ADAPTER] Schwab parse error: {e}")
            return None


class RobinhoodAdapter(BaseBrokerAdapter):
    BROKER_NAME = 'robinhood'
    HAS_PRECISE_FILL_TIME = False
    
    def parse_fill(self, raw_order: Dict) -> Optional[BrokerFillData]:
        try:
            filled_at = self.normalize_timestamp(
                raw_order.get('last_transaction_at') or raw_order.get('created_at')
            )
            if not filled_at:
                filled_at = datetime.now()
            
            return BrokerFillData(
                broker=self.BROKER_NAME,
                order_id=str(raw_order.get('id', '')),
                symbol=raw_order.get('symbol', ''),
                asset_type='option' if raw_order.get('chain_symbol') else 'stock',
                side=raw_order.get('side', 'buy').upper(),
                quantity=int(float(raw_order.get('cumulative_quantity', 0))),
                fill_price=float(raw_order.get('average_price', 0)),
                filled_at=filled_at,
                raw_data=raw_order
            )
        except Exception as e:
            print(f"[ADAPTER] Robinhood parse error: {e}")
            return None


class IBKRAdapter(BaseBrokerAdapter):
    BROKER_NAME = 'ibkr'
    HAS_PRECISE_FILL_TIME = True
    
    def parse_fill(self, raw_order: Dict) -> Optional[BrokerFillData]:
        try:
            filled_at = self.normalize_timestamp(raw_order.get('lastExecutionTime'))
            if not filled_at:
                filled_at = datetime.now()
            
            return BrokerFillData(
                broker=self.BROKER_NAME,
                order_id=str(raw_order.get('orderId', '')),
                symbol=raw_order.get('symbol', ''),
                asset_type='option' if raw_order.get('secType') == 'OPT' else 'stock',
                side=raw_order.get('side', 'BUY'),
                quantity=int(raw_order.get('filledQuantity', 0)),
                fill_price=float(raw_order.get('avgFillPrice', 0)),
                filled_at=filled_at,
                strike=raw_order.get('strike'),
                expiry=raw_order.get('lastTradeDateOrContractMonth'),
                call_put=raw_order.get('right'),
                raw_data=raw_order
            )
        except Exception as e:
            print(f"[ADAPTER] IBKR parse error: {e}")
            return None


class QuestradeAdapter(BaseBrokerAdapter):
    BROKER_NAME = 'questrade'
    HAS_PRECISE_FILL_TIME = False
    
    def parse_fill(self, raw_order: Dict) -> Optional[BrokerFillData]:
        try:
            filled_at = self.normalize_timestamp(raw_order.get('updateTime') or raw_order.get('creationTime'))
            if not filled_at:
                filled_at = datetime.now()
            
            return BrokerFillData(
                broker=self.BROKER_NAME,
                order_id=str(raw_order.get('id', '')),
                symbol=raw_order.get('symbol', ''),
                asset_type='option' if raw_order.get('orderClass') == 'Option' else 'stock',
                side=raw_order.get('side', 'Buy'),
                quantity=int(raw_order.get('filledQuantity', 0)),
                fill_price=float(raw_order.get('avgExecPrice', 0)),
                filled_at=filled_at,
                raw_data=raw_order
            )
        except Exception as e:
            print(f"[ADAPTER] Questrade parse error: {e}")
            return None


class UpstoxAdapter(BaseBrokerAdapter):
    BROKER_NAME = 'upstox'
    HAS_PRECISE_FILL_TIME = True
    
    def parse_fill(self, raw_order: Dict) -> Optional[BrokerFillData]:
        try:
            filled_at = self.normalize_timestamp(raw_order.get('order_timestamp') or raw_order.get('exchange_timestamp'))
            if not filled_at:
                filled_at = datetime.now()
            
            return BrokerFillData(
                broker=self.BROKER_NAME,
                order_id=str(raw_order.get('order_id', '')),
                symbol=raw_order.get('tradingsymbol', ''),
                asset_type='option' if raw_order.get('instrument_type') in ['CE', 'PE'] else 'stock',
                side=raw_order.get('transaction_type', 'BUY'),
                quantity=int(raw_order.get('filled_quantity', 0)),
                fill_price=float(raw_order.get('average_price', 0)),
                filled_at=filled_at,
                raw_data=raw_order
            )
        except Exception as e:
            print(f"[ADAPTER] Upstox parse error: {e}")
            return None


class ZerodhaAdapter(BaseBrokerAdapter):
    BROKER_NAME = 'zerodha'
    HAS_PRECISE_FILL_TIME = True
    
    def parse_fill(self, raw_order: Dict) -> Optional[BrokerFillData]:
        try:
            filled_at = self.normalize_timestamp(raw_order.get('order_timestamp') or raw_order.get('exchange_timestamp'))
            if not filled_at:
                filled_at = datetime.now()
            
            return BrokerFillData(
                broker=self.BROKER_NAME,
                order_id=str(raw_order.get('order_id', '')),
                symbol=raw_order.get('tradingsymbol', ''),
                asset_type='option' if raw_order.get('instrument_type') in ['CE', 'PE'] else 'stock',
                side=raw_order.get('transaction_type', 'BUY'),
                quantity=int(raw_order.get('filled_quantity', 0)),
                fill_price=float(raw_order.get('average_price', 0)),
                filled_at=filled_at,
                raw_data=raw_order
            )
        except Exception as e:
            print(f"[ADAPTER] Zerodha parse error: {e}")
            return None


class DhanQAdapter(BaseBrokerAdapter):
    BROKER_NAME = 'dhanq'
    HAS_PRECISE_FILL_TIME = True
    
    def parse_fill(self, raw_order: Dict) -> Optional[BrokerFillData]:
        try:
            filled_at = self.normalize_timestamp(raw_order.get('orderUpdateTime') or raw_order.get('orderCreationTime'))
            if not filled_at:
                filled_at = datetime.now()
            
            return BrokerFillData(
                broker=self.BROKER_NAME,
                order_id=str(raw_order.get('orderId', '')),
                symbol=raw_order.get('tradingSymbol', ''),
                asset_type='option' if raw_order.get('productType') == 'OPTION' else 'stock',
                side=raw_order.get('transactionType', 'BUY'),
                quantity=int(raw_order.get('filledQty', 0)),
                fill_price=float(raw_order.get('price', 0)),
                filled_at=filled_at,
                raw_data=raw_order
            )
        except Exception as e:
            print(f"[ADAPTER] DhanQ parse error: {e}")
            return None


BROKER_ADAPTERS = {
    'webull': WebullAdapter(),
    'alpaca': AlpacaAdapter(),
    'tastytrade': TastytradeAdapter(),
    'schwab': SchwabAdapter(),
    'robinhood': RobinhoodAdapter(),
    'ibkr': IBKRAdapter(),
    'questrade': QuestradeAdapter(),
    'upstox': UpstoxAdapter(),
    'zerodha': ZerodhaAdapter(),
    'dhanq': DhanQAdapter(),
}


def get_adapter(broker_name: str) -> BaseBrokerAdapter:
    broker_key = broker_name.lower().replace(' ', '').replace('_', '')
    return BROKER_ADAPTERS.get(broker_key, BaseBrokerAdapter())


def parse_broker_fill(broker_name: str, raw_order: Dict) -> Optional[BrokerFillData]:
    adapter = get_adapter(broker_name)
    return adapter.parse_fill(raw_order)
