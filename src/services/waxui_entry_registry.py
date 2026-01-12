"""
WaxUI Entry Registry - Links updates to original entries.

Tracks active WaxUI positions to enable:
- Update signals to reference correct position
- Trim percentages to calculate quantities
- Trail stops to use correct entry price for B/E

Supports WaxUI signal formats:
- Entry: "SPX here 12/05 6880C Avg. 4.00"
- Trim: "Trim SPX here 4.00 - 4.80 ✓ 20% Holding most."
- More: "More SPX here 4.00 - 5.50 ✓ 38%"
- Hold: "Holding runners only."
- Trail: "Trail stops set @B/E"
- Close: "Closed SPX here"
"""

import re
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum


class HoldingState(Enum):
    FULL = 'full'
    MOST = 'most'
    MAJORITY = 'majority'
    HALF = 'half'
    RUNNERS = 'runners'
    CLOSED = 'closed'


@dataclass
class WaxUIEntry:
    ticker: str
    expiry: str
    strike: float
    opt_type: str
    entry_price: float
    quantity: int
    channel_id: str
    signal_instance_id: Optional[int] = None
    current_price: Optional[float] = None
    profit_pct: float = 0.0
    holding_state: HoldingState = HoldingState.FULL
    trailing_stop_enabled: bool = False
    trailing_stop_price: Optional[float] = None
    is_lotto: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


class WaxUIEntryRegistry:
    """
    Registry for active WaxUI positions.
    
    Provides lookup by ticker to link update signals to original entries.
    """
    
    WAXUI_ENTRY_PATTERN = re.compile(
        r'([A-Za-z]+)\s+here\s+(\d{1,2})/(\d{1,2})\s+(\d+(?:\.\d+)?)\s*([CPcp])\s+[Aa]vg[.,]?\s*(\.?\d+\.?\d*)',
        re.IGNORECASE
    )
    WAXUI_TRIM_PATTERN = re.compile(r'[Tt]rim\s+([A-Za-z]+)\s+here', re.IGNORECASE)
    WAXUI_CLOSE_PATTERN = re.compile(r'[Cc]lose[d]?\s+([A-Za-z]+)\s+here', re.IGNORECASE)
    WAXUI_MORE_PATTERN = re.compile(r'[Mm]ore\s+([A-Za-z]+)\s+here', re.IGNORECASE)
    WAXUI_PROFIT_LADDER_PATTERN = re.compile(r'(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)\s*[✓✔️☑]?\s*(\d+)%')
    WAXUI_TRAIL_STOPS_PATTERN = re.compile(
        r'[Tt]rail\s*stops?\s+(?:set\s+)?@\s*([Bb]/[Ee]|[Bb]reak\s*even|[0-9.]+)',
        re.IGNORECASE
    )
    WAXUI_LOTTO_PATTERN = re.compile(r'LOTTO|[Ll]otto')
    
    WAXUI_HOLDING_PATTERNS = {
        HoldingState.MOST: re.compile(r'[Hh]olding\s+most', re.IGNORECASE),
        HoldingState.MAJORITY: re.compile(r'[Hh]olding\s+majority', re.IGNORECASE),
        HoldingState.HALF: re.compile(r'[Hh]olding\s+1/2|[Hh]olding\s+half', re.IGNORECASE),
        HoldingState.RUNNERS: re.compile(r'[Hh]olding\s+runners\s+only', re.IGNORECASE),
    }
    
    HOLDING_TO_PCT_REMAINING = {
        HoldingState.FULL: 100,
        HoldingState.MOST: 75,
        HoldingState.MAJORITY: 60,
        HoldingState.HALF: 50,
        HoldingState.RUNNERS: 25,
        HoldingState.CLOSED: 0,
    }
    
    def __init__(self, ttl_hours: int = 48):
        self._entries: Dict[str, WaxUIEntry] = {}
        self._ttl_hours = ttl_hours
    
    def _make_key(self, ticker: str, expiry: str = None, strike: float = None) -> str:
        """Create lookup key. Expiry/strike optional for fuzzy matching."""
        if expiry and strike:
            return f"{ticker.upper()}_{expiry}_{strike}"
        return ticker.upper()
    
    def register_entry(self, entry: WaxUIEntry) -> str:
        """Register a new WaxUI entry."""
        key = self._make_key(entry.ticker, entry.expiry, entry.strike)
        self._entries[key] = entry
        self._cleanup_expired()
        print(f"[WAXUI REGISTRY] Registered: {entry.ticker} {entry.expiry} {entry.strike}{entry.opt_type} @ ${entry.entry_price}")
        return key
    
    def find_by_ticker(self, ticker: str) -> Optional[WaxUIEntry]:
        """Find most recent entry by ticker (for updates without expiry/strike)."""
        ticker_upper = ticker.upper()
        matches = [e for k, e in self._entries.items() if e.ticker.upper() == ticker_upper]
        if matches:
            return max(matches, key=lambda e: e.created_at)
        return None
    
    def find_by_full_key(self, ticker: str, expiry: str, strike: float) -> Optional[WaxUIEntry]:
        """Find entry by exact ticker/expiry/strike."""
        key = self._make_key(ticker, expiry, strike)
        return self._entries.get(key)
    
    def update_holding_state(
        self, 
        ticker: str, 
        state: HoldingState, 
        current_price: float = None, 
        profit_pct: float = None
    ) -> Optional[WaxUIEntry]:
        """Update holding state from trim/more signals."""
        entry = self.find_by_ticker(ticker)
        if entry:
            entry.holding_state = state
            entry.updated_at = datetime.now()
            if current_price:
                entry.current_price = current_price
            if profit_pct:
                entry.profit_pct = profit_pct
            print(f"[WAXUI REGISTRY] Updated {ticker}: state={state.value}, profit={profit_pct}%")
            return entry
        return None
    
    def set_trailing_stop(
        self, 
        ticker: str, 
        price: float = None, 
        at_breakeven: bool = False
    ) -> Optional[WaxUIEntry]:
        """Set trailing stop. If at_breakeven, use entry price."""
        entry = self.find_by_ticker(ticker)
        if entry:
            entry.trailing_stop_enabled = True
            if at_breakeven:
                entry.trailing_stop_price = entry.entry_price
                print(f"[WAXUI REGISTRY] {ticker}: Trailing stop set to B/E @ ${entry.entry_price}")
            elif price:
                entry.trailing_stop_price = price
                print(f"[WAXUI REGISTRY] {ticker}: Trailing stop set @ ${price}")
            entry.updated_at = datetime.now()
            return entry
        return None
    
    def close_entry(self, ticker: str) -> Optional[WaxUIEntry]:
        """Mark entry as closed and remove from registry."""
        entry = self.find_by_ticker(ticker)
        if entry:
            entry.holding_state = HoldingState.CLOSED
            key = self._make_key(entry.ticker, entry.expiry, entry.strike)
            del self._entries[key]
            print(f"[WAXUI REGISTRY] Closed: {ticker}")
            return entry
        return None
    
    def get_remaining_pct(self, ticker: str) -> int:
        """Get estimated remaining position percentage based on holding state."""
        entry = self.find_by_ticker(ticker)
        if entry:
            return self.HOLDING_TO_PCT_REMAINING.get(entry.holding_state, 100)
        return 100
    
    def _cleanup_expired(self):
        """Remove entries older than TTL."""
        cutoff = datetime.now() - timedelta(hours=self._ttl_hours)
        expired = [k for k, e in self._entries.items() if e.created_at < cutoff]
        for k in expired:
            del self._entries[k]
            print(f"[WAXUI REGISTRY] Expired: {k}")
    
    def get_all_entries(self) -> List[WaxUIEntry]:
        """Get all active entries."""
        self._cleanup_expired()
        return list(self._entries.values())
    
    def parse_signal(self, text: str, channel_id: str) -> Optional[Dict]:
        """
        Complete WaxUI signal parser with update linking.
        
        Handles all WaxUI signal types and returns structured data.
        """
        result = {
            'type': 'waxui',
            'action': None,
            'symbol': None,
            'entry_price': None,
            'current_price': None,
            'profit_pct': None,
            'holding_state': None,
            'trailing_stop': None,
            'is_lotto': bool(self.WAXUI_LOTTO_PATTERN.search(text)),
            'signal_instance_id': None,
        }
        
        m = self.WAXUI_ENTRY_PATTERN.search(text)
        if m:
            symbol, month, day, strike, opt_type, price = m.groups()
            result['action'] = 'BTO'
            result['symbol'] = symbol.upper()
            result['expiry'] = f"{month}/{day}"
            result['strike'] = float(strike)
            result['opt_type'] = opt_type.upper()
            result['entry_price'] = float(price.lstrip('.'))
            
            entry = WaxUIEntry(
                ticker=result['symbol'],
                expiry=result['expiry'],
                strike=result['strike'],
                opt_type=result['opt_type'],
                entry_price=result['entry_price'],
                quantity=0,
                channel_id=channel_id,
                is_lotto=result['is_lotto']
            )
            self.register_entry(entry)
            return result
        
        m = self.WAXUI_CLOSE_PATTERN.search(text)
        if m:
            symbol = m.group(1).upper()
            result['action'] = 'STC'
            result['symbol'] = symbol
            result['exit_type'] = 'close'
            
            entry = self.close_entry(symbol)
            if entry:
                result['signal_instance_id'] = entry.signal_instance_id
            return result
        
        m = self.WAXUI_TRIM_PATTERN.search(text)
        if m:
            symbol = m.group(1).upper()
            result['action'] = 'TRIM'
            result['symbol'] = symbol
            
            ladder = self.WAXUI_PROFIT_LADDER_PATTERN.search(text)
            if ladder:
                result['entry_price'] = float(ladder.group(1))
                result['current_price'] = float(ladder.group(2))
                result['profit_pct'] = float(ladder.group(3))
            
            for state, pattern in self.WAXUI_HOLDING_PATTERNS.items():
                if pattern.search(text):
                    result['holding_state'] = state.value
                    self.update_holding_state(
                        symbol, state,
                        result.get('current_price'),
                        result.get('profit_pct')
                    )
                    break
            
            return result
        
        m = self.WAXUI_MORE_PATTERN.search(text)
        if m:
            symbol = m.group(1).upper()
            result['action'] = 'UPDATE'
            result['symbol'] = symbol
            
            ladder = self.WAXUI_PROFIT_LADDER_PATTERN.search(text)
            if ladder:
                result['entry_price'] = float(ladder.group(1))
                result['current_price'] = float(ladder.group(2))
                result['profit_pct'] = float(ladder.group(3))
            
            for state, pattern in self.WAXUI_HOLDING_PATTERNS.items():
                if pattern.search(text):
                    result['holding_state'] = state.value
                    self.update_holding_state(
                        symbol, state,
                        result.get('current_price'),
                        result.get('profit_pct')
                    )
                    break
            
            return result
        
        m = self.WAXUI_TRAIL_STOPS_PATTERN.search(text)
        if m:
            trail_value = m.group(1)
            
            ticker_match = re.search(r'([A-Z]{1,5})', text)
            symbol = ticker_match.group(1) if ticker_match else None
            
            result['action'] = 'TRAIL_STOP'
            result['symbol'] = symbol
            
            if 'B/E' in trail_value.upper() or 'BREAK' in trail_value.upper():
                result['trailing_stop'] = 'breakeven'
                if symbol:
                    self.set_trailing_stop(symbol, at_breakeven=True)
            else:
                try:
                    result['trailing_stop'] = float(trail_value)
                    if symbol:
                        self.set_trailing_stop(symbol, price=float(trail_value))
                except ValueError:
                    pass
            
            return result
        
        for state, pattern in self.WAXUI_HOLDING_PATTERNS.items():
            if pattern.search(text):
                ticker_match = re.search(r'([A-Z]{2,5})', text)
                if ticker_match:
                    symbol = ticker_match.group(1)
                    result['action'] = 'HOLD_UPDATE'
                    result['symbol'] = symbol
                    result['holding_state'] = state.value
                    
                    ladder = self.WAXUI_PROFIT_LADDER_PATTERN.search(text)
                    if ladder:
                        result['entry_price'] = float(ladder.group(1))
                        result['current_price'] = float(ladder.group(2))
                        result['profit_pct'] = float(ladder.group(3))
                    
                    self.update_holding_state(symbol, state)
                    return result
        
        return None


waxui_registry = WaxUIEntryRegistry()
