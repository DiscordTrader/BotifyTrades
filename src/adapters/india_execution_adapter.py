"""
India Market Execution Adapter

Converts parsed Indian market signals to broker-specific formats for:
- Zerodha (Kite Connect) - Trading symbol format
- Upstox - Instrument token format
- DhanQ - Security ID format

Handles:
- Symbol resolution (NIFTY, BANKNIFTY, stocks)
- Lot size calculation
- Expiry date formatting
- Exchange segment selection
"""

import re
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum


class IndiaExchange(Enum):
    NSE_EQ = "NSE_EQ"      # NSE Equity
    NSE_FNO = "NSE_FNO"    # NSE F&O
    BSE_EQ = "BSE_EQ"      # BSE Equity
    BSE_FNO = "BSE_FNO"    # BSE F&O
    MCX_COMM = "MCX_COMM"  # MCX Commodity


class IndiaProductType(Enum):
    CNC = "CNC"          # Cash and Carry (delivery)
    MIS = "MIS"          # Margin Intraday Square-off
    NRML = "NRML"        # Normal (F&O overnight)
    INTRADAY = "INTRADAY"


class OrderIntent(Enum):
    BUY_TO_OPEN = "BTO"
    SELL_TO_OPEN = "STO"
    BUY_TO_CLOSE = "BTC"
    SELL_TO_CLOSE = "STC"


@dataclass
class IndiaInstrument:
    """Represents an Indian market instrument with broker-specific identifiers"""
    symbol: str
    strike: Optional[float]
    option_type: Optional[str]  # CE/PE
    expiry: Optional[str]       # YYYY-MM-DD
    exchange: IndiaExchange
    product: IndiaProductType
    lot_size: int
    
    # Broker-specific identifiers
    kite_symbol: Optional[str] = None      # e.g., NIFTY25JAN24000CE
    upstox_token: Optional[str] = None     # Instrument token
    dhan_security_id: Optional[int] = None # Security ID


# NSE Lot Sizes (as of 2025)
NSE_LOT_SIZES = {
    'NIFTY': 25,
    'BANKNIFTY': 15,
    'FINNIFTY': 25,
    'MIDCPNIFTY': 50,
    'SENSEX': 10,
    'BANKEX': 15,
    'RELIANCE': 250,
    'TCS': 150,
    'INFY': 300,
    'HDFCBANK': 550,
    'ICICIBANK': 1375,
    'SBIN': 1500,
    'TATAMOTORS': 1425,
    'TATASTEEL': 1500,
    'ITC': 1600,
    'HINDUNILVR': 300,
    'BAJFINANCE': 125,
    'LT': 150,
    'AXISBANK': 600,
    'KOTAKBANK': 400,
    'MARUTI': 100,
    'BHARTIARTL': 950,
    'ASIANPAINT': 200,
    'WIPRO': 1500,
    'HCLTECH': 350,
    'ADANIENT': 250,
    'ADANIPORTS': 1250,
    'COALINDIA': 2100,
    'ONGC': 3850,
    'POWERGRID': 2700,
    'NTPC': 2925,
    'SUNPHARMA': 700,
    'TITAN': 375,
    'TECHM': 300,
    'ULTRACEMCO': 100,
}

# DhanQ Security IDs for common instruments
DHAN_SECURITY_IDS = {
    'NIFTY': 26000,
    'BANKNIFTY': 26009,
    'FINNIFTY': 26037,
    'MIDCPNIFTY': 26074,
    'RELIANCE': 2885,
    'TCS': 11536,
    'INFY': 1594,
    'HDFCBANK': 1333,
    'ICICIBANK': 4963,
    'SBIN': 3045,
    'TATAMOTORS': 3456,
    'TATASTEEL': 3499,
    'ITC': 1660,
    'HINDUNILVR': 1394,
    'BAJFINANCE': 317,
    'LT': 11483,
    'AXISBANK': 5900,
    'KOTAKBANK': 1922,
    'MARUTI': 10999,
    'BHARTIARTL': 10604,
}

# Month abbreviations for Kite symbol construction
MONTH_ABBR = {
    1: 'JAN', 2: 'FEB', 3: 'MAR', 4: 'APR',
    5: 'MAY', 6: 'JUN', 7: 'JUL', 8: 'AUG',
    9: 'SEP', 10: 'OCT', 11: 'NOV', 12: 'DEC'
}


class IndiaExecutionAdapter:
    """
    Adapter for executing Indian market trades across multiple brokers.
    
    Converts parsed signal data to broker-specific formats and handles:
    - Symbol resolution
    - Expiry date calculation
    - Lot size management
    - Exchange/product selection
    """
    
    def __init__(self):
        self.lot_sizes = NSE_LOT_SIZES.copy()
        self.dhan_ids = DHAN_SECURITY_IDS.copy()
    
    def resolve_instrument(self, parsed_signal: Dict[str, Any]) -> IndiaInstrument:
        """
        Resolve a parsed signal to a fully qualified instrument.
        
        Args:
            parsed_signal: Output from parse_india_option_signal or parse_india_stock_signal
            
        Returns:
            IndiaInstrument with broker-specific identifiers
        """
        symbol = parsed_signal.get('symbol', '').upper()
        asset_type = parsed_signal.get('asset', 'option')
        strike = parsed_signal.get('strike')
        opt_type = parsed_signal.get('opt_type', parsed_signal.get('call_put'))
        expiry_str = parsed_signal.get('expiry')
        
        # Determine exchange and product
        if asset_type == 'option':
            exchange = IndiaExchange.NSE_FNO
            product = IndiaProductType.NRML
        else:
            exchange = IndiaExchange.NSE_EQ
            product = IndiaProductType.CNC
        
        # Get lot size
        lot_size = self.lot_sizes.get(symbol, 1)
        
        # Parse expiry
        expiry_date = self._parse_expiry(expiry_str) if expiry_str else self._get_next_expiry(symbol)
        
        # Build broker-specific identifiers
        kite_symbol = self._build_kite_symbol(symbol, strike, opt_type, expiry_date, asset_type)
        dhan_security_id = self.dhan_ids.get(symbol)
        
        return IndiaInstrument(
            symbol=symbol,
            strike=strike,
            option_type=opt_type,
            expiry=expiry_date.strftime('%Y-%m-%d') if expiry_date else None,
            exchange=exchange,
            product=product,
            lot_size=lot_size,
            kite_symbol=kite_symbol,
            upstox_token=None,  # Requires API lookup
            dhan_security_id=dhan_security_id
        )
    
    def determine_intent(self, parsed_signal: Dict[str, Any], 
                         has_open_position: bool = False) -> OrderIntent:
        """
        Determine the true order intent from the signal.
        
        Indian markets commonly use:
        - BUY to open long positions
        - SELL to either open shorts OR close longs
        
        Args:
            parsed_signal: Parsed signal data
            has_open_position: Whether there's an existing position to close
            
        Returns:
            OrderIntent enum value
        """
        action = parsed_signal.get('action', '').upper()
        direction = parsed_signal.get('direction', action).upper()
        
        # Check for explicit intent markers
        explicit_intent = parsed_signal.get('intent')
        if explicit_intent:
            intent_map = {
                'BTO': OrderIntent.BUY_TO_OPEN,
                'STO': OrderIntent.SELL_TO_OPEN,
                'BTC': OrderIntent.BUY_TO_CLOSE,
                'STC': OrderIntent.SELL_TO_CLOSE,
            }
            return intent_map.get(explicit_intent.upper(), OrderIntent.BUY_TO_OPEN)
        
        # Infer intent from action and position state
        if direction in ('BUY', 'BTO'):
            if has_open_position:
                return OrderIntent.BUY_TO_CLOSE  # Covering a short
            return OrderIntent.BUY_TO_OPEN
        elif direction in ('SELL', 'STC', 'STO'):
            if has_open_position:
                return OrderIntent.SELL_TO_CLOSE  # Closing a long
            return OrderIntent.SELL_TO_OPEN  # Opening a short
        
        return OrderIntent.BUY_TO_OPEN
    
    def prepare_zerodha_order(self, instrument: IndiaInstrument, 
                               parsed_signal: Dict[str, Any],
                               intent: OrderIntent) -> Dict[str, Any]:
        """
        Prepare order parameters for Zerodha Kite Connect.
        
        Args:
            instrument: Resolved instrument
            parsed_signal: Original parsed signal
            intent: Order intent
            
        Returns:
            Dict with Kite-compatible order parameters
        """
        # Determine transaction type
        if intent in (OrderIntent.BUY_TO_OPEN, OrderIntent.BUY_TO_CLOSE):
            transaction_type = 'BUY'
        else:
            transaction_type = 'SELL'
        
        # Calculate quantity
        lots = parsed_signal.get('lots', 1)
        quantity = lots * instrument.lot_size
        
        # Determine exchange
        if instrument.option_type:
            exchange = 'NFO'
        else:
            exchange = 'NSE'
        
        # Determine product type
        product = 'NRML' if instrument.option_type else 'CNC'
        
        order_params = {
            'tradingsymbol': instrument.kite_symbol,
            'exchange': exchange,
            'transaction_type': transaction_type,
            'quantity': quantity,
            'order_type': 'LIMIT' if parsed_signal.get('price') else 'MARKET',
            'product': product,
            'validity': 'DAY',
        }
        
        if parsed_signal.get('price'):
            order_params['price'] = float(parsed_signal['price'])
        
        return order_params
    
    def prepare_upstox_order(self, instrument: IndiaInstrument,
                              parsed_signal: Dict[str, Any],
                              intent: OrderIntent) -> Dict[str, Any]:
        """
        Prepare order parameters for Upstox.
        
        Note: Upstox requires instrument_token which needs API lookup.
        """
        if intent in (OrderIntent.BUY_TO_OPEN, OrderIntent.BUY_TO_CLOSE):
            transaction_type = 'BUY'
        else:
            transaction_type = 'SELL'
        
        lots = parsed_signal.get('lots', 1)
        quantity = lots * instrument.lot_size
        
        # Determine segment
        if instrument.option_type:
            segment = 'NSE_FO'
        else:
            segment = 'NSE_EQ'
        
        order_params = {
            'instrument_token': instrument.upstox_token,  # Needs API lookup
            'quantity': quantity,
            'transaction_type': transaction_type,
            'order_type': 'LIMIT' if parsed_signal.get('price') else 'MARKET',
            'product': 'INTRADAY' if not instrument.option_type else 'NRML',
            'validity': 'DAY',
            'segment': segment,
        }
        
        if parsed_signal.get('price'):
            order_params['price'] = float(parsed_signal['price'])
        else:
            order_params['price'] = 0
        
        return order_params
    
    def prepare_dhanq_order(self, instrument: IndiaInstrument,
                             parsed_signal: Dict[str, Any],
                             intent: OrderIntent) -> Dict[str, Any]:
        """
        Prepare order parameters for DhanQ.
        """
        if intent in (OrderIntent.BUY_TO_OPEN, OrderIntent.BUY_TO_CLOSE):
            transaction_type = 'BUY'
        else:
            transaction_type = 'SELL'
        
        lots = parsed_signal.get('lots', 1)
        quantity = lots * instrument.lot_size
        
        order_params = {
            'security_id': instrument.dhan_security_id,
            'exchange_segment': instrument.exchange.value,
            'transaction_type': transaction_type,
            'quantity': quantity,
            'order_type': 'LIMIT' if parsed_signal.get('price') else 'MARKET',
            'product_type': instrument.product.value,
            'validity': 'DAY',
        }
        
        if parsed_signal.get('price'):
            order_params['price'] = float(parsed_signal['price'])
        
        return order_params
    
    def _build_kite_symbol(self, symbol: str, strike: Optional[float],
                           opt_type: Optional[str], expiry: Optional[datetime],
                           asset_type: str) -> str:
        """
        Build Kite Connect trading symbol.
        
        Format for options: NIFTY25JAN24000CE
        Format for stocks: RELIANCE
        """
        if asset_type == 'stock' or not opt_type:
            return symbol
        
        if not expiry:
            expiry = self._get_next_expiry(symbol)
        
        # Format: SYMBOL + YY + MMM + STRIKE + CE/PE
        year_suffix = expiry.strftime('%y')
        month_abbr = MONTH_ABBR[expiry.month]
        strike_int = int(strike) if strike else 0
        opt_suffix = 'CE' if opt_type in ('C', 'CE', 'CALL') else 'PE'
        
        return f"{symbol}{year_suffix}{month_abbr}{strike_int}{opt_suffix}"
    
    def _parse_expiry(self, expiry_str: str) -> Optional[datetime]:
        """
        Parse expiry string to datetime.
        
        Supports formats:
        - "MM/DD" (e.g., "01/02")
        - "DD MMM YYYY" (e.g., "02 JAN 2025")
        - "DDMMMYY" (e.g., "02JAN25")
        """
        if not expiry_str:
            return None
        
        expiry_str = expiry_str.strip().upper()
        
        # Try MM/DD format
        if '/' in expiry_str:
            parts = expiry_str.split('/')
            if len(parts) == 2:
                try:
                    month = int(parts[0])
                    day = int(parts[1])
                    year = datetime.now().year
                    return datetime(year, month, day)
                except ValueError:
                    pass
        
        # Try DD MMM YYYY format
        match = re.match(r'(\d{1,2})\s*(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s*(\d{2,4})?', expiry_str)
        if match:
            day = int(match.group(1))
            month_str = match.group(2)
            year_str = match.group(3)
            
            month_map = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
                        'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
            month = month_map.get(month_str, 1)
            
            if year_str:
                year = int(year_str)
                if year < 100:
                    year += 2000
            else:
                year = datetime.now().year
            
            return datetime(year, month, day)
        
        return None
    
    def _get_next_expiry(self, symbol: str) -> datetime:
        """
        Get the next expiry date for a symbol.
        
        NSE Expiry Schedule (effective September 2025):
        - NIFTY: Weekly (Tuesday) - only index with weekly options
        - BANKNIFTY/FINNIFTY/MIDCPNIFTY: Monthly only (last Tuesday)
        - Stock options: Monthly (last Tuesday)
        """
        today = datetime.now()
        
        weekly_symbols = {'NIFTY'}
        
        if symbol in weekly_symbols:
            target_weekday = 1
            
            days_ahead = target_weekday - today.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            
            return today + timedelta(days=days_ahead)
        else:
            next_month = today.replace(day=28) + timedelta(days=4)
            last_day = next_month - timedelta(days=next_month.day)
            
            days_to_tuesday = (last_day.weekday() - 1) % 7
            last_tuesday = last_day - timedelta(days=days_to_tuesday)
            
            if last_tuesday <= today:
                next_month = (today.replace(day=28) + timedelta(days=35)).replace(day=28) + timedelta(days=4)
                last_day = next_month - timedelta(days=next_month.day)
                days_to_tuesday = (last_day.weekday() - 1) % 7
                last_tuesday = last_day - timedelta(days=days_to_tuesday)
            
            return last_tuesday
    
    def format_inr_currency(self, amount: float) -> str:
        """Format amount as Indian Rupees with proper notation."""
        if amount >= 10000000:  # 1 Crore
            return f"₹{amount / 10000000:.2f} Cr"
        elif amount >= 100000:  # 1 Lakh
            return f"₹{amount / 100000:.2f} L"
        elif amount >= 1000:
            return f"₹{amount:,.2f}"
        else:
            return f"₹{amount:.2f}"
    
    def get_lot_size(self, symbol: str) -> int:
        """Get lot size for a symbol."""
        return self.lot_sizes.get(symbol.upper(), 1)
    
    def is_india_symbol(self, symbol: str) -> bool:
        """Check if a symbol is an Indian market symbol."""
        india_indices = {'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX', 'BANKEX'}
        india_stocks = set(self.lot_sizes.keys())
        
        symbol_upper = symbol.upper()
        return symbol_upper in india_indices or symbol_upper in india_stocks


# Singleton instance
_adapter_instance = None

def get_india_adapter() -> IndiaExecutionAdapter:
    """Get singleton instance of India execution adapter."""
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = IndiaExecutionAdapter()
    return _adapter_instance
