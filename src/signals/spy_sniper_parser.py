"""
Spy-Sniper Signal Parser
=========================
Parses signals from the spy-sniper Discord channel format.

Signal Types:
- Open Alert: Entry signal (BTO)
- Trim Alert: Partial exit signal (STC partial)
- Close Alert: Full exit signal (STC all)

Signal Format:
- Entry: "SPY 1/16 691P .44" (symbol expiry strikeC/P price)
- Exit: "SPY 1/15 691P\n.44 ➡️ 1.32 🟢 200%" (symbol expiry strikeC/P\nentry ➡️ current 🟢 gain%)
"""

import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from enum import Enum


class SpySniperSignalType(Enum):
    ENTRY = "entry"           # Open Alert → BTO
    TRIM = "trim"             # Trim Alert → STC partial
    CLOSE = "close"           # Close Alert → STC all
    UNKNOWN = "unknown"


@dataclass
class SpySniperSignal:
    signal_type: SpySniperSignalType
    symbol: str
    expiry: str              # Raw format: "1/16"
    expiry_date: str         # Normalized: "2026-01-16"
    strike: float
    option_type: str         # "C" or "P"
    entry_price: Optional[float] = None
    current_price: Optional[float] = None
    gain_percent: Optional[int] = None
    is_full_exit: bool = False
    message_id: Optional[str] = None
    raw_text: str = ""
    
    @property
    def option_key(self) -> str:
        """Generate unique key for position matching."""
        return f"{self.symbol}_{self.expiry_date}_{self.strike}_{self.option_type}"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_type": self.signal_type.value,
            "symbol": self.symbol,
            "expiry": self.expiry,
            "expiry_date": self.expiry_date,
            "strike": self.strike,
            "option_type": self.option_type,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "gain_percent": self.gain_percent,
            "is_full_exit": self.is_full_exit,
            "option_key": self.option_key,
            "message_id": self.message_id,
            "raw_text": self.raw_text
        }


OPTION_PATTERN = re.compile(
    r'([A-Z]{1,5})\s+'                         # Symbol: SPY
    r'(\d{1,2}/\d{1,2})\s*'                    # Expiry: 1/16 (optional space after)
    r'(\d+(?:\.\d+)?)\s*([CP])\s*'             # Strike + Type: 691P or 695C
    r'(\.?\d+(?:\.\d+)?)?',                    # Entry Price: .44 (optional) - dot INSIDE capture
    re.IGNORECASE
)

GAIN_PATTERN = re.compile(
    r'(\.?\d+(?:\.\d+)?)\s*'                   # Entry price: .44 - dot INSIDE capture
    r'[\u2192➡️→]+\s*'                          # Arrow: ➡️
    r'(\.?\d+(?:\.\d+)?)\s*'                   # Current price: 1.32 - dot INSIDE capture
    r'[\U0001F7E2🟢]*\s*'                       # Green emoji (optional)
    r'(\d+)\s*%',                              # Gain percent: 200%
    re.IGNORECASE
)

FULL_EXIT_PHRASES = [
    "i'm all out",
    "all out",
    "closed",
    "stopped out",
    "stopped me out",
    "stopped me back out",
    "got stopped out"
]


def is_spy_sniper_signal(embed_title: Optional[str], embed_description: Optional[str] = None) -> bool:
    """
    Check if embed is a valid spy-sniper trading signal.
    
    Returns True ONLY if:
    1. Title contains 'open alert', 'trim alert', or 'close alert'
    2. Description contains a valid option pattern (e.g., SPY 1/16 691P)
    
    This prevents forwarding @everyone posts, charts, or other non-trade content.
    """
    if not embed_title:
        return False
    
    title_lower = embed_title.lower()
    
    signal_titles = ['open alert', 'trim alert', 'close alert']
    
    if not any(sig in title_lower for sig in signal_titles):
        return False
    
    if not embed_description:
        return False
    
    option_match = OPTION_PATTERN.search(embed_description)
    if not option_match:
        return False
    
    return True


def detect_signal_type(embed_title: Optional[str], embed_description: Optional[str] = None) -> SpySniperSignalType:
    """Detect signal type from embed title and description."""
    if not embed_title:
        return SpySniperSignalType.UNKNOWN
    
    title_lower = embed_title.lower()
    desc_lower = (embed_description or "").lower()
    
    if 'open alert' in title_lower:
        return SpySniperSignalType.ENTRY
    
    if 'close alert' in title_lower:
        return SpySniperSignalType.CLOSE
    
    if 'trim alert' in title_lower:
        if any(phrase in desc_lower for phrase in FULL_EXIT_PHRASES):
            return SpySniperSignalType.CLOSE
        return SpySniperSignalType.TRIM
    
    return SpySniperSignalType.UNKNOWN


def normalize_expiry(expiry_str: str) -> str:
    """Convert any expiry format to YYYY-MM-DD."""
    from src.core.expiry import normalize_expiry_iso
    try:
        return normalize_expiry_iso(expiry_str)
    except ValueError:
        return expiry_str


def parse_option_signal(text: str) -> Optional[Dict[str, Any]]:
    """Parse option details from signal text."""
    match = OPTION_PATTERN.search(text)
    if not match:
        return None
    
    symbol = match.group(1).upper()
    expiry = match.group(2)
    strike = float(match.group(3))
    option_type = match.group(4).upper()
    
    price = None
    if match.group(5):
        price_str = match.group(5)
        # Handle leading dot format: ".37" should become 0.37
        if price_str.startswith('.'):
            price = float('0' + price_str)
        else:
            price = float(price_str)
    
    normalized = normalize_expiry(expiry)
    return {
        "symbol": symbol,
        "expiry": normalized,
        "expiry_date": normalized,
        "strike": strike,
        "option_type": option_type,
        "price": price
    }


def parse_gain_info(text: str) -> Optional[Dict[str, Any]]:
    """Parse entry price, current price, and gain from exit signal."""
    match = GAIN_PATTERN.search(text)
    if not match:
        return None
    
    entry_str = match.group(1)
    current_str = match.group(2)
    
    entry_price = float(entry_str) if not entry_str.startswith('.') else float('0' + entry_str)
    current_price = float(current_str) if not current_str.startswith('.') else float('0' + current_str)
    
    if entry_price < 1 and not entry_str.startswith('0'):
        entry_price = float('0.' + entry_str.lstrip('.'))
    if current_price < 1 and not current_str.startswith('0'):
        current_price = float('0.' + current_str.lstrip('.'))
    
    gain_percent = int(match.group(3))
    
    return {
        "entry_price": entry_price,
        "current_price": current_price,
        "gain_percent": gain_percent
    }


def parse_spy_sniper_signal(
    embed_title: Optional[str],
    embed_description: str,
    message_id: Optional[str] = None
) -> Optional[SpySniperSignal]:
    """
    Parse a spy-sniper signal from Discord embed.
    
    Args:
        embed_title: The embed title (e.g., "Open Alert", "Trim Alert", "Close Alert")
        embed_description: The embed description containing option details
        message_id: Optional Discord message ID for deduplication
        
    Returns:
        SpySniperSignal object or None if parsing fails
    """
    if not is_spy_sniper_signal(embed_title, embed_description):
        return None
    
    signal_type = detect_signal_type(embed_title, embed_description)
    if signal_type == SpySniperSignalType.UNKNOWN:
        return None
    
    option_data = parse_option_signal(embed_description)
    if not option_data:
        return None
    
    gain_data = None
    if signal_type in [SpySniperSignalType.TRIM, SpySniperSignalType.CLOSE]:
        gain_data = parse_gain_info(embed_description)
    
    desc_lower = embed_description.lower()
    is_full_exit = (
        signal_type == SpySniperSignalType.CLOSE or
        any(phrase in desc_lower for phrase in FULL_EXIT_PHRASES)
    )
    
    return SpySniperSignal(
        signal_type=signal_type,
        symbol=option_data["symbol"],
        expiry=option_data["expiry"],
        expiry_date=option_data["expiry_date"],
        strike=option_data["strike"],
        option_type=option_data["option_type"],
        entry_price=gain_data["entry_price"] if gain_data else option_data.get("price"),
        current_price=gain_data["current_price"] if gain_data else None,
        gain_percent=gain_data["gain_percent"] if gain_data else None,
        is_full_exit=is_full_exit,
        message_id=message_id,
        raw_text=embed_description
    )


def format_as_bto(
    signal: SpySniperSignal,
    quantity: Optional[int] = None,
    dollar_amount: Optional[float] = None
) -> Optional[str]:
    """
    Format entry signal as BTO for webhook forwarding.
    
    Args:
        signal: Parsed spy-sniper signal
        quantity: Fixed quantity (contracts)
        dollar_amount: Dollar amount to calculate quantity from
        
    Returns:
        Formatted BTO string
    """
    if signal.signal_type != SpySniperSignalType.ENTRY:
        return None
    
    qty_str = ""
    if quantity:
        qty_str = f"{quantity} "
    elif dollar_amount and signal.entry_price:
        calculated_qty = int(dollar_amount / (signal.entry_price * 100))
        if calculated_qty < 1:
            calculated_qty = 1
        qty_str = f"{calculated_qty} "
    
    price_str = f"@ {signal.entry_price}" if signal.entry_price else "@ m"
    
    return f"BTO {qty_str}{signal.symbol} {signal.expiry} {signal.strike}{signal.option_type} {price_str}"


def format_as_stc(
    signal: SpySniperSignal,
    quantity: Optional[int] = None,
    exit_percentage: Optional[int] = None
) -> Optional[str]:
    """
    Format exit signal as STC for webhook forwarding.
    
    Args:
        signal: Parsed spy-sniper signal
        quantity: Explicit quantity to exit
        exit_percentage: Percentage of position to exit (for partial exits)
        
    Returns:
        Formatted STC string
    """
    if signal.signal_type not in [SpySniperSignalType.TRIM, SpySniperSignalType.CLOSE]:
        return None
    
    exit_note = ""
    if signal.is_full_exit:
        exit_note = " (ALL)"
    elif exit_percentage:
        exit_note = f" ({exit_percentage}%)"
    
    qty_str = f"{quantity} " if quantity else ""
    
    price_str = f"@ {signal.current_price}" if signal.current_price else ""
    
    gain_str = f" +{signal.gain_percent}%" if signal.gain_percent else ""
    
    return f"STC {qty_str}{signal.symbol} {signal.expiry} {signal.strike}{signal.option_type} {price_str}{gain_str}{exit_note}"


DEFAULT_EXIT_SCHEDULE = {
    15: 20,    # At 15% gain → exit 20%
    50: 20,    # At 50% gain → exit 20%
    100: 20,   # At 100% gain → exit 20%
    150: 20,   # At 150% gain → exit 20%
    200: 20,   # At 200%+ gain → exit remaining
}


class SpySniperPositionTracker:
    """
    Tracks open positions for partial exit calculations.
    Uses gain-threshold-based exits with trim-count fallback.
    """
    
    def __init__(self, exit_schedule: Optional[Dict[int, int]] = None):
        self.positions: Dict[str, Dict] = {}
        self.exit_schedule = exit_schedule or DEFAULT_EXIT_SCHEDULE
        self.processed_signals: set = set()
    
    def _get_dedup_key(self, message_id: str, option_key: str, action: str) -> str:
        """Generate deduplication key."""
        return f"{message_id}_{action}_{option_key}"
    
    def is_duplicate(self, message_id: str, option_key: str, action: str) -> bool:
        """Check if signal was already processed."""
        dedup_key = self._get_dedup_key(message_id, option_key, action)
        return dedup_key in self.processed_signals
    
    def mark_processed(self, message_id: str, option_key: str, action: str):
        """Mark signal as processed."""
        dedup_key = self._get_dedup_key(message_id, option_key, action)
        self.processed_signals.add(dedup_key)
    
    def handle_entry(self, signal: SpySniperSignal, quantity: int) -> bool:
        """
        Handle entry signal - create position record.
        
        Returns:
            True if position was created, False if duplicate
        """
        msg_id = signal.message_id or ""
        if msg_id and self.is_duplicate(msg_id, signal.option_key, "BTO"):
            return False
        
        self.positions[signal.option_key] = {
            "entry_price": signal.entry_price,
            "quantity": quantity,
            "remaining_qty": quantity,
            "remaining_pct": 100,
            "trim_count": 0,
            "gain_thresholds_hit": [],
            "entry_time": datetime.now().isoformat(),
            "entry_message_id": msg_id
        }
        
        if msg_id:
            self.mark_processed(msg_id, signal.option_key, "BTO")
        return True
    
    def handle_exit(self, signal: SpySniperSignal) -> Tuple[Optional[int], Optional[int]]:
        """
        Handle exit signal - calculate exit quantity.
        
        Returns:
            Tuple of (exit_quantity, exit_percentage) or (None, None) if no position
        """
        msg_id = signal.message_id or ""
        if msg_id and self.is_duplicate(msg_id, signal.option_key, "STC"):
            return None, None
        
        position = self.positions.get(signal.option_key)
        if not position:
            print(f"[SPY-SNIPER] ⚠️ No matching position for {signal.option_key}")
            return None, None
        
        if signal.is_full_exit:
            exit_qty = position["remaining_qty"]
            exit_pct = position["remaining_pct"]
            del self.positions[signal.option_key]
            if msg_id:
                self.mark_processed(msg_id, signal.option_key, "STC")
            return exit_qty, exit_pct
        
        gain_pct = signal.gain_percent if signal.gain_percent is not None else 0
        exit_pct = self._calculate_exit_percentage(position, gain_pct)
        
        exit_qty = max(1, int(position["quantity"] * exit_pct / 100))
        exit_qty = min(exit_qty, position["remaining_qty"])
        
        position["remaining_qty"] -= exit_qty
        position["remaining_pct"] -= exit_pct
        position["trim_count"] += 1
        
        if position["remaining_qty"] <= 0:
            del self.positions[signal.option_key]
        
        if msg_id:
            self.mark_processed(msg_id, signal.option_key, "STC")
        return exit_qty, exit_pct
    
    def _calculate_exit_percentage(self, position: Dict, gain_pct: int = 0) -> int:
        """Calculate exit percentage based on gain threshold or trim count."""
        
        if gain_pct > 0:
            hit_thresholds = position.get("gain_thresholds_hit", [])
            
            for threshold, exit_pct in sorted(self.exit_schedule.items()):
                if gain_pct >= threshold and threshold not in hit_thresholds:
                    hit_thresholds.append(threshold)
                    position["gain_thresholds_hit"] = hit_thresholds
                    return exit_pct
        
        trim_count = position.get("trim_count", 0)
        if trim_count == 0:
            return 25
        elif trim_count == 1:
            return 25
        elif trim_count == 2:
            return 25
        else:
            return position.get("remaining_pct", 100)
    
    def get_position(self, option_key: str) -> Optional[Dict]:
        """Get position data for a given option key."""
        return self.positions.get(option_key)
    
    def get_all_positions(self) -> Dict[str, Dict]:
        """Get all open positions."""
        return self.positions.copy()
    
    def clear_stale_positions(self, max_age_hours: int = 24):
        """Remove positions older than max_age_hours."""
        now = datetime.now()
        stale_keys = []
        
        for key, pos in self.positions.items():
            try:
                entry_time = datetime.fromisoformat(pos["entry_time"])
                age_hours = (now - entry_time).total_seconds() / 3600
                if age_hours > max_age_hours:
                    stale_keys.append(key)
            except Exception:
                pass
        
        for key in stale_keys:
            print(f"[SPY-SNIPER] Clearing stale position: {key}")
            del self.positions[key]
        
        return len(stale_keys)


_position_tracker: Optional[SpySniperPositionTracker] = None


def get_position_tracker() -> SpySniperPositionTracker:
    """Get the global position tracker instance."""
    global _position_tracker
    if _position_tracker is None:
        _position_tracker = SpySniperPositionTracker()
    return _position_tracker


def process_spy_sniper_message(
    embed_title: str,
    embed_description: str,
    message_id: str,
    default_quantity: int = 1,
    default_dollar_amount: Optional[float] = None
) -> Optional[Dict[str, Any]]:
    """
    Process a spy-sniper message and return formatted webhook signal.
    
    Args:
        embed_title: Discord embed title
        embed_description: Discord embed description
        message_id: Discord message ID
        default_quantity: Default contract quantity for entries
        default_dollar_amount: Dollar amount to calculate quantity
        
    Returns:
        Dict with 'action' (BTO/STC), 'signal', 'formatted_message', 'quantity'
    """
    signal = parse_spy_sniper_signal(embed_title, embed_description, message_id)
    if not signal:
        return None
    
    tracker = get_position_tracker()
    
    if signal.signal_type == SpySniperSignalType.ENTRY:
        qty = default_quantity
        entry_price = signal.entry_price or 0.0
        if default_dollar_amount and entry_price > 0:
            qty = max(1, int(default_dollar_amount / (entry_price * 100)))
        
        if not tracker.handle_entry(signal, qty):
            print(f"[SPY-SNIPER] Duplicate entry signal skipped: {signal.option_key}")
            return None
        
        formatted_msg = format_as_bto(signal, quantity=qty)
        
        return {
            "action": "BTO",
            "signal": signal.to_dict(),
            "formatted_message": formatted_msg,
            "quantity": qty,
            "option_key": signal.option_key
        }
    
    elif signal.signal_type in [SpySniperSignalType.TRIM, SpySniperSignalType.CLOSE]:
        exit_qty, exit_pct = tracker.handle_exit(signal)
        
        if exit_qty is None:
            return None
        
        formatted_msg = format_as_stc(signal, quantity=exit_qty, exit_percentage=exit_pct)
        
        return {
            "action": "STC",
            "signal": signal.to_dict(),
            "formatted_message": formatted_msg,
            "quantity": exit_qty,
            "exit_percentage": exit_pct,
            "option_key": signal.option_key,
            "is_full_exit": signal.is_full_exit
        }
    
    return None
