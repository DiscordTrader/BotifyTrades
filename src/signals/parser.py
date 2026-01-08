"""
Signal parser for trading signals.
Parses option and stock signals from text messages.
"""

import re
from typing import Optional, Dict, Any

from .patterns import (
    FLEXIBLE_OPT_PATTERN,
    DEFAULT_STK_PATTERN,
    create_option_regex,
    create_stock_regex,
    INDIA_PATTERNS,
    INDIA_OPT_PATTERN_ABOVE,
    INDIA_OPT_PATTERN_EXPIRY_FIRST,
    INDIA_OPT_PATTERN_NO_PRICE,
    INDIA_STK_PATTERN,
    INDIA_MONTH_MAP,
    NSE_LOT_SIZES,
)


# Bullwinkle format patterns - comprehensive support
# Entry emoji indicators: :green_alert: or 🟢
BULLWINKLE_ENTRY_INDICATORS = [':green_alert:', '🟢', ':greenalert:']
BULLWINKLE_EXIT_INDICATORS = [':SirenRed:', ':sirenred:', '🔴', ':red_circle:', ':red_alert:', ':redalert:']

# Entry patterns (multiple variants)
# Pattern 1: :green_alert: BTO 3 AMPX | $11 C .95 2/20 (with BTO keyword and qty prefix)
BULLWINKLE_ENTRY_BTO_QTY = re.compile(
    r'(?::?green_alert:?|🟢)\s*BTO\s+(\d+)\s+\$?([A-Z]+)\s*\|\s*\$?([\d.]+)\s*([CP])\s*([\d.]+)(?:\s+(.+?))?$',
    re.IGNORECASE
)

# Pattern 2: 🟢BTO $RKT | 21.2 C JAN/16 .56 5 cons (with BTO, expiry, qty at end)
BULLWINKLE_ENTRY_BTO_QTY_END = re.compile(
    r'(?::?green_alert:?|🟢)\s*BTO\s+\$?([A-Z]+)\s*\|\s*\$?([\d.]+)\s*([CP])\s+([A-Z]+\s*/?\s*\d+|\d+/\d+|NEXT\s*WEEK)\s+([\d.]+)\s+(\d+)\s*(?:cons?|contracts?)?',
    re.IGNORECASE
)

# Pattern 3: :green_alert: SYMBOL | $STRIKE C/P PRICE EXPIRY (standard scalp - price before expiry text)
BULLWINKLE_ENTRY_STANDARD = re.compile(
    r'(?::?green_alert:?|🟢)\s*\$?([A-Z]+)\s*\|\s*\$?([\d.]+)\s*([CP])\s+([\d.]+)(?:\s+(.+?))?$',
    re.IGNORECASE
)

# Pattern 4: :green_alert: SYMBOL | STRIKE C EXPIRY PRICE (price at end after expiry)
BULLWINKLE_ENTRY_PRICE_END = re.compile(
    r'(?::?green_alert:?|🟢)\s*\$?([A-Z]+)\s*\|\s*\$?([\d.]+)\s*([CP])\s+([A-Z]+\s*/?\s*\d+|\d+/\d+|NEXT\s*WEEK|[A-Z]+\s*/?\s*\d{4}|[A-Z]+\s+\d{4}|[A-Z]+)\s+([\d.]+)$',
    re.IGNORECASE
)

# Pattern 5: :green_alert: SYMBOL | $STRIKE PRICE EXPIRY (no C/P, assume call)
# Example: :green_alert: TSLA | $492.5 10.10 JAN 2ND
BULLWINKLE_ENTRY_NO_CP = re.compile(
    r'(?::?green_alert:?|🟢)\s*\$?([A-Z]+)\s*\|\s*\$?([\d.]+)\s+([\d.]+)\s+([A-Z]+\s*\d+(?:ST|ND|RD|TH)?|[A-Z]+\s*/?\s*\d+|\d+/\d+)',
    re.IGNORECASE
)

# Exit patterns (multiple variants)
# Pattern 1: :SirenRed: STC ALL $AMPX ✅ (STC keyword without price)
BULLWINKLE_EXIT_STC_ALL = re.compile(
    r'(?::?SirenRed:?|🔴)\s*STC\s+(?:ALL|\d+)\s+\$?([A-Z]+)',
    re.IGNORECASE
)

# Pattern 2: :SirenRed: STC 4 RKT @ .75 SL .70 (STC with qty and price)
BULLWINKLE_EXIT_STC_QTY_PRICE = re.compile(
    r'(?::?SirenRed:?|🔴)\s*STC\s+(\d+)\s+\$?([A-Z]+)\s*@?\s*([\d.]+)',
    re.IGNORECASE
)

# Pattern 3: :SirenRed: STC $SYMBOL | .70 OUT ALL ✅ (STC with pipe and OUT)
BULLWINKLE_EXIT_STC_PIPE = re.compile(
    r'(?::?SirenRed:?|🔴)\s*STC\s+\$?([A-Z]+)\s*\|\s*([\d.]+)\s*OUT',
    re.IGNORECASE
)

# Pattern 4: :SirenRed: SYMBOL | PRICE OUT ... (original pattern)
BULLWINKLE_EXIT_PIPE_PRICE = re.compile(
    r'(?::?SirenRed:?|🔴)\s*\$?([A-Z]+)\s*\|\s*([\d.]+)\s*OUT',
    re.IGNORECASE
)

# Pattern 5: :SirenRed: SYMBOL | OUT @ PRICE ... (OUT @ format)
BULLWINKLE_EXIT_OUT_AT = re.compile(
    r'(?::?SirenRed:?|🔴)\s*\$?([A-Z]+)\s*\|\s*OUT\s*@?\s*([\d.]+)',
    re.IGNORECASE
)

# Pattern 6: :SirenRed: PLTR 1.40OUT ALL (no space before OUT)
BULLWINKLE_EXIT_NO_SPACE = re.compile(
    r'(?::?SirenRed:?|🔴)\s*\$?([A-Z]+)\s+([\d.]+)OUT',
    re.IGNORECASE
)

# Pattern 7: :SirenRed: STC $SYMBOL OUT ALL BUT 1 $PRICE (complex format)
BULLWINKLE_EXIT_COMPLEX = re.compile(
    r'(?::?SirenRed:?|🔴)\s*STC\s+\$?([A-Z]+)\s+OUT\s+.*?\$?([\d.]+)',
    re.IGNORECASE
)

# Legacy patterns for backward compatibility
BULLWINKLE_ENTRY_PATTERN = BULLWINKLE_ENTRY_STANDARD
BULLWINKLE_EXIT_PATTERN = BULLWINKLE_EXIT_PIPE_PRICE

# ============ CONDITIONAL ORDER PATTERNS ============
# These patterns detect price-triggered conditional orders
# Examples:
#   "LVRO over 1.30 SL 10% profit target 1.43"
#   "AAPL over 250 10% of ACCOUNT PT 260 SL 240"
#   "SPY under 680 stop loss 2% take profit 675"

# Main conditional trigger pattern: SYMBOL over/under PRICE
CONDITIONAL_TRIGGER_PATTERN = re.compile(
    r'(?:^|\s)\$?([A-Z]{1,5})\s+(?:over|above)\s+\$?([\d.]+)',
    re.IGNORECASE
)

CONDITIONAL_TRIGGER_UNDER_PATTERN = re.compile(
    r'(?:^|\s)\$?([A-Z]{1,5})\s+(?:under|below)\s+\$?([\d.]+)',
    re.IGNORECASE
)

# Stop loss patterns for conditional orders
CONDITIONAL_SL_PERCENT_PATTERN = re.compile(
    r'(?:SL|stop\s*loss|stop)\s*[:\s]*(\d+(?:\.\d+)?)\s*%',
    re.IGNORECASE
)

CONDITIONAL_SL_FIXED_PATTERN = re.compile(
    r'(?:SL|stop\s*loss|stop)\s*[:\s@]*\$?([\d.]+)(?!\s*%)',
    re.IGNORECASE
)

# Profit target patterns for conditional orders
CONDITIONAL_PT_PATTERN = re.compile(
    r'(?:PT|profit\s*target|target|take\s*profit|TP)\s*[:\s@]*\$?([\d.]+)',
    re.IGNORECASE
)

# Multiple profit targets: PT 1.43, 1.50, 1.60
CONDITIONAL_MULTI_PT_PATTERN = re.compile(
    r'(?:PT|profit\s*target|targets?|take\s*profit|TP)\s*[:\s]*\$?([\d.]+)(?:[,\s]+\$?([\d.]+))?(?:[,\s]+\$?([\d.]+))?(?:[,\s]+\$?([\d.]+))?',
    re.IGNORECASE
)

# Position sizing: 10% of ACCOUNT, 10% ACCOUNT, 10% portfolio
CONDITIONAL_POSITION_SIZE_PATTERN = re.compile(
    r'(\d+(?:\.\d+)?)\s*%\s*(?:of\s*)?(?:account|portfolio|capital)',
    re.IGNORECASE
)

# Fixed quantity: 100 shares, 50 contracts, qty 100
CONDITIONAL_QTY_PATTERN = re.compile(
    r'(?:qty|quantity)?\s*(\d+)\s*(?:shares?|contracts?|cons?)?',
    re.IGNORECASE
)

# ============ EXTENDED CONDITIONAL ORDER PATTERNS ============
# Target ranges: "first target 16.60-17", "second target 35-35.50"
CONDITIONAL_TARGET_RANGE_PATTERN = re.compile(
    r'(?:(?P<tier>first|second|third|fourth|1st|2nd|3rd|4th)\s+)?'
    r'(?:target|tgt|pt)\s*[:\s]*\$?(?P<min_price>[\d.]+)\s*[-–—to]+\s*\$?(?P<max_price>[\d.]+)',
    re.IGNORECASE
)

# Partial exit patterns: "selling 80% MLTX", "selling 60%", "selling half"
PARTIAL_EXIT_PATTERN = re.compile(
    r'(?:selling|sold|trimm?(?:ing|ed)?|taking\s+(?:off|profit))\s+'
    r'(?:(?P<percent>\d+(?:\.\d+)?)\s*%|(?P<fraction>half|quarter|third))\s*'
    r'(?:of\s+)?(?:my\s+)?(?:position\s+)?(?:in\s+)?'
    r'(?:\$?(?P<symbol>[A-Z]{1,5}))?',
    re.IGNORECASE
)

# Leaving runner pattern: "leaving 10%", "leaving 20% MLTX"
LEAVING_RUNNER_PATTERN = re.compile(
    r'(?:leaving|keeping)\s+(?P<percent>\d+(?:\.\d+)?)\s*%\s*'
    r'(?:of\s+)?(?:my\s+)?(?:position\s+)?(?:in\s+)?'
    r'(?:\$?(?P<symbol>[A-Z]{1,5}))?',
    re.IGNORECASE
)

# Cancellation pattern: "@Daytrades cancelling JTAI", "cancel JTAI"
CANCEL_ORDER_PATTERN = re.compile(
    r'(?:cancell?(?:ing|ed)?|cancel|stopped?\s+out|closing\s+watch)\s+'
    r'(?:on\s+)?(?:the\s+)?(?:order\s+)?(?:for\s+)?'
    r'\$?(?P<symbol>[A-Z]{1,5})',
    re.IGNORECASE
)

# Hybrid stop loss pattern: "SL 8.15 or 6%", "stop loss 14.60 or 5%"
HYBRID_SL_PATTERN = re.compile(
    r'(?:SL|stop\s*loss|stop)\s*[:\s@]*'
    r'(?:\$?(?P<fixed>[\d.]+)\s*(?:or|/)\s*(?P<pct>[\d.]+)\s*%|'
    r'(?P<pct_first>[\d.]+)\s*%\s*(?:or|/)\s*\$?(?P<fixed_second>[\d.]+))',
    re.IGNORECASE
)

# Follow-up message patterns for sequential monitoring
# Detects delayed SL/PT updates: "SL now at 14.60", "PT raised to 17.50"
FOLLOW_UP_SL_PATTERN = re.compile(
    r'(?:SL|stop\s*loss|stop)\s*'
    r'(?:now\s+)?(?:at|moved?\s+to|raised?\s+to|lowered?\s+to|changed?\s+to|updated?\s+to|set\s+(?:at|to))?\s*'
    r'[:\s@]*\$?(?P<price>[\d.]+)(?:\s*%)?',
    re.IGNORECASE
)

FOLLOW_UP_PT_PATTERN = re.compile(
    r'(?:PT|target|profit\s*target|take\s*profit|TP)\s*'
    r'(?:now\s+)?(?:at|moved?\s+to|raised?\s+to|changed?\s+to|updated?\s+to|set\s+(?:at|to))?\s*'
    r'[:\s@]*\$?(?P<price>[\d.]+)',
    re.IGNORECASE
)

# Z-Scalps format patterns (simple pipe format WITHOUT emojis)
# Entry: TSLA | $460 C NEXT WEEK 7.15 @everyone
# Entry: SPY | $680 P 1.82 @everyone (immediate price after C/P)
ZSCALPS_ENTRY_PATTERN = re.compile(
    r'(?:^|\s)([A-Z]{1,5})\s*\|\s*\$?([\d.]+)\s*([CP])\s+(.+?)\s+([\d.]+)(?:\s|@everyone|$)',
    re.IGNORECASE | re.MULTILINE
)

# Entry variant: TSLA | $460 C 7.15 (price right after C/P with optional expiry after)
# Also handles: SPY | $680 P 1.82 @everyone
ZSCALPS_ENTRY_PRICE_FIRST = re.compile(
    r'(?:^|\s)([A-Z]{1,5})\s*\|\s*\$?([\d.]+)\s*([CP])\s+([\d.]+)(?:\s+(.+?))?(?:\s|@everyone|$)',
    re.IGNORECASE | re.MULTILINE
)

# Exit: TSLA | 7.45 OUT (or TSLA | 7.45 OUT ALL, SPY | 1.91 OUT HALF)
ZSCALPS_EXIT_PATTERN = re.compile(
    r'(?:^|\s)([A-Z]{1,5})\s*\|\s*([\d.]+)\s*OUT',
    re.IGNORECASE | re.MULTILINE
)

# Exit variant: TSLA | PRICE PENDING ORDER TO EXIT HALF
ZSCALPS_EXIT_PENDING = re.compile(
    r'(?:^|\s)([A-Z]{1,5})\s*\|\s*([\d.]+)\s*PENDING\s+ORDER',
    re.IGNORECASE | re.MULTILINE
)

# TRADE IDEA format patterns (C1apped style)
TRADE_IDEA_TICKER_PATTERN = re.compile(
    r'(?:📌\s*)?(?:Ticker|Symbol):\s*\$?([A-Z]+)',
    re.IGNORECASE
)
TRADE_IDEA_ENTRY_PATTERN = re.compile(
    r'(?:💰\s*)?Entry:\s*\$?([\d.]+)',
    re.IGNORECASE
)
TRADE_IDEA_LEVELS_PATTERN = re.compile(
    r'(?:📈\s*)?(?:Levels|Targets|PTs?):\s*([\d.\s\-\+]+)',
    re.IGNORECASE
)
TRADE_IDEA_SL_PATTERN = re.compile(
    r'(?:⛔\s*)?(?:SL|Stop\s*Loss|Stop):\s*\$?([\d.]+)',
    re.IGNORECASE
)

# Bracket order format patterns (stock signals with targets and stop loss)
# Example: BTO ENSC @ $2.02 (break)\nTargets: $2.1, $2.16, $2.22\nSL: $1.78
BRACKET_BTO_PATTERN = re.compile(
    r'BTO\s+\$?([A-Z]+)\s*@\s*\$?([\d.]+)(?:\s*\(([^)]+)\))?',
    re.IGNORECASE
)
BRACKET_TARGETS_PATTERN = re.compile(
    r'Targets?:\s*([\d.$,\s]+)',
    re.IGNORECASE
)
BRACKET_SL_PATTERN = re.compile(
    r'SL:\s*\$?([\d.]+)',
    re.IGNORECASE
)

# Jacob format patterns (ENTERED LONG/SHORT stock signals with bracket order data)
# Example: ENTERED LONG: $SIDU, ENTRY: $4.00 AREA, S.L: $3.68, 1st Target: $4.32-4.37
JACOB_ENTERED_PATTERN = re.compile(
    r'ENTERED\s+(LONG|SHORT):\s*\$?([A-Z]{1,5})',
    re.IGNORECASE
)
JACOB_ENTRY_PATTERN = re.compile(
    r'ENTRY:\s*\$?([\d.]+)',
    re.IGNORECASE
)
JACOB_SL_PATTERN = re.compile(
    r'S\.?L\.?:[\s\u200e\u200f\u202a-\u202e]*\$?([\d.]+)',
    re.IGNORECASE
)
JACOB_TARGET_PATTERN = re.compile(
    r'(?:1st\s+)?Target:\s*\$?([\d.]+)',
    re.IGNORECASE
)


def parse_trade_idea(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse TRADE IDEA format signals (C1apped style).
    
    Example:
    | TRADE IDEA
    📌 Ticker: TRIB
    💰 Entry: 1.36
    📈 Levels: 1.45 - 1.49 - 1.56 - 1.65 - 1.77+
    ⛔ SL: 1.22
    
    Returns dict with parsed components or None if not a TRADE IDEA.
    """
    if 'TRADE IDEA' not in text.upper():
        return None
    
    ticker_match = TRADE_IDEA_TICKER_PATTERN.search(text)
    entry_match = TRADE_IDEA_ENTRY_PATTERN.search(text)
    levels_match = TRADE_IDEA_LEVELS_PATTERN.search(text)
    sl_match = TRADE_IDEA_SL_PATTERN.search(text)
    
    if not ticker_match or not entry_match:
        return None
    
    ticker = ticker_match.group(1).upper()
    entry_price = float(entry_match.group(1))
    
    stop_loss = float(sl_match.group(1)) if sl_match else None
    
    profit_targets = []
    if levels_match:
        levels_str = levels_match.group(1)
        levels_str = re.sub(r'[+\s]+$', '', levels_str)
        for level in re.split(r'\s*[-–]\s*', levels_str):
            try:
                level_clean = re.sub(r'[^\d.]', '', level.strip())
                if level_clean:
                    profit_targets.append(float(level_clean))
            except ValueError:
                pass
    
    is_exit = 'all out' in text.lower() or 'closed' in text.lower() or 'exited' in text.lower()
    
    result = {
        'format': 'TRADE_IDEA',
        'ticker': ticker,
        'symbol': ticker,
        'entry_price': entry_price,
        'price': entry_price,
        'stop_loss': stop_loss,
        'profit_targets': profit_targets,
        'is_exit': is_exit,
        'action': 'STC' if is_exit else 'BTO',
        'asset': 'stock',
        'asset_type': 'stock',
        'qty': 1,
        '_qty_from_signal': False,
        '_trade_idea': True,
    }
    
    print(f"[TRADE IDEA] ✓ Parsed: {ticker} @ {entry_price}, SL={stop_loss}, PTs={profit_targets}")
    return result


def is_trade_idea_signal(text: str) -> bool:
    """Check if text is a TRADE IDEA format signal."""
    return 'TRADE IDEA' in text.upper() and (
        TRADE_IDEA_TICKER_PATTERN.search(text) is not None or
        TRADE_IDEA_ENTRY_PATTERN.search(text) is not None
    )


def is_jacob_signal(text: str) -> bool:
    """Check if text is a Jacob format signal (ENTERED LONG/SHORT)."""
    return JACOB_ENTERED_PATTERN.search(text) is not None and JACOB_ENTRY_PATTERN.search(text) is not None


JACOB_POSITION_SIZE_PATTERN = re.compile(r'([\d.]+)\s*%\s*(?:OF\s*)?ACCOUNT', re.IGNORECASE)

def parse_jacob_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse Jacob format stock signals with bracket order data.
    
    Example:
    12.5% OF ACCOUNT
    ENTERED LONG: $SIDU
    ENTRY: $4.00 AREA
    S.L: $3.68
    1st Target: $4.32-4.37
    
    Returns dict with parsed components or None if not a Jacob format signal.
    """
    entered_match = JACOB_ENTERED_PATTERN.search(text)
    if not entered_match:
        return None
    
    direction = entered_match.group(1).upper()  # LONG or SHORT
    ticker = entered_match.group(2).upper()
    
    # Extract entry price
    entry_match = JACOB_ENTRY_PATTERN.search(text)
    if not entry_match:
        return None
    entry_price = float(entry_match.group(1))
    
    # Extract position size percentage (e.g., "12.5% OF ACCOUNT")
    position_size_pct = None
    pct_match = JACOB_POSITION_SIZE_PATTERN.search(text)
    if pct_match:
        position_size_pct = float(pct_match.group(1))
    
    # Extract stop loss
    stop_loss = None
    sl_match = JACOB_SL_PATTERN.search(text)
    if sl_match:
        stop_loss = float(sl_match.group(1))
    
    # Extract target
    targets = []
    target_match = JACOB_TARGET_PATTERN.search(text)
    if target_match:
        targets.append(float(target_match.group(1)))
    
    # Determine action based on direction
    action = 'BTO' if direction == 'LONG' else 'STO'  # STO for short selling
    
    result = {
        'format': 'JACOB',
        'ticker': ticker,
        'symbol': ticker,
        'entry_price': entry_price,
        'price': entry_price,
        'stop_loss': stop_loss,
        'profit_targets': targets,
        'action': action,
        'direction': direction,
        'asset': 'stock',
        'asset_type': 'stock',
        '_qty_from_signal': False,
        '_jacob_signal': True,
        '_bracket_order': True,
        '_calculate_qty': True,  # Signal that qty should be calculated from position sizing
    }
    
    # Add position size percentage if found
    if position_size_pct:
        result['_position_size_pct'] = position_size_pct
        print(f"[JACOB] ✓ Parsed: {action} {ticker} @ {entry_price}, {position_size_pct}% position, SL={stop_loss}, PTs={targets}")
    else:
        print(f"[JACOB] ✓ Parsed: {action} {ticker} @ {entry_price}, SL={stop_loss}, PTs={targets}")
    
    return result


def format_jacob_for_webhook(parsed: Dict[str, Any]) -> str:
    """Format a parsed Jacob signal as BTO/STC for webhook forwarding.
    
    Outputs format: BTO $SYMBOL @ price (percentage%)
    SL: $X
    Targets: $Y, $Z
    
    If position size percentage is specified, includes it in the message.
    Stop loss and targets are included on separate lines for bracket order execution.
    """
    action = parsed.get('action', 'BTO')
    symbol = parsed.get('symbol', '')
    price = parsed.get('entry_price', parsed.get('price', 0))
    position_pct = parsed.get('_position_size_pct')
    stop_loss = parsed.get('stop_loss')
    profit_targets = parsed.get('profit_targets', [])
    
    # Build main line: BTO $SYMBOL @ price (with optional position size percentage)
    if position_pct:
        result = f"{action} ${symbol} @ {price:.2f} ({position_pct}%)"
    else:
        result = f"{action} ${symbol} @ {price:.2f}"
    
    # Add stop loss on new line if present
    if stop_loss:
        result += f"\nSL: ${stop_loss:.2f}"
    
    # Add targets on new line if present
    if profit_targets and len(profit_targets) > 0:
        targets_str = ', '.join([f"${t:.2f}" for t in profit_targets])
        result += f"\nTargets: {targets_str}"
    
    return result


def is_conditional_order_signal(text: str) -> bool:
    """
    Check if text is a conditional order signal (price-triggered entry).
    
    Conditional orders require explicit 'over/above' or 'under/below' keywords
    to distinguish from regular BTO/STC signals.
    """
    text_upper = text.upper()
    
    # Must have over/under trigger AND at least one of SL/PT
    has_over_trigger = CONDITIONAL_TRIGGER_PATTERN.search(text) is not None
    has_under_trigger = CONDITIONAL_TRIGGER_UNDER_PATTERN.search(text) is not None
    
    if not (has_over_trigger or has_under_trigger):
        return False
    
    # Must have SL or PT to be a valid conditional order (not just a price mention)
    has_sl = CONDITIONAL_SL_PERCENT_PATTERN.search(text) or CONDITIONAL_SL_FIXED_PATTERN.search(text)
    has_pt = CONDITIONAL_PT_PATTERN.search(text)
    has_position_size = CONDITIONAL_POSITION_SIZE_PATTERN.search(text)
    
    # Require at least one of: SL, PT, or position size
    return bool(has_sl or has_pt or has_position_size)


def parse_conditional_order_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse conditional order signal (price-triggered entry with SL/PT).
    
    Examples:
        "LVRO over 1.30 SL 10% profit target 1.43"
        "AAPL over 250 10% of ACCOUNT PT 260 SL 240"
        "SPY under 680 stop loss 2% take profit 675"
    
    Returns dict with parsed conditional order or None if not matched.
    """
    if not is_conditional_order_signal(text):
        return None
    
    # Try to match over/above trigger
    trigger_match = CONDITIONAL_TRIGGER_PATTERN.search(text)
    trigger_type = 'over'
    
    if not trigger_match:
        # Try under/below trigger
        trigger_match = CONDITIONAL_TRIGGER_UNDER_PATTERN.search(text)
        trigger_type = 'under'
    
    if not trigger_match:
        return None
    
    symbol = trigger_match.group(1).upper()
    trigger_price = float(trigger_match.group(2))
    
    # Parse stop loss - check for hybrid first (e.g., "SL 8.15 or 6%")
    stop_loss_type = None
    stop_loss_value = None
    stop_loss_fixed = None
    stop_loss_pct = None
    
    hybrid_sl_match = HYBRID_SL_PATTERN.search(text)
    if hybrid_sl_match:
        # Hybrid SL: both fixed and percent
        fixed = hybrid_sl_match.group('fixed') or hybrid_sl_match.group('fixed_second')
        pct = hybrid_sl_match.group('pct') or hybrid_sl_match.group('pct_first')
        if fixed and pct:
            stop_loss_type = 'hybrid'
            stop_loss_fixed = float(fixed)
            stop_loss_pct = float(pct)
            stop_loss_value = stop_loss_fixed  # Primary value for backwards compatibility
    
    if not stop_loss_type:
        sl_pct_match = CONDITIONAL_SL_PERCENT_PATTERN.search(text)
        if sl_pct_match:
            stop_loss_type = 'percent'
            stop_loss_value = float(sl_pct_match.group(1))
            stop_loss_pct = stop_loss_value
        else:
            sl_fixed_match = CONDITIONAL_SL_FIXED_PATTERN.search(text)
            if sl_fixed_match:
                stop_loss_type = 'fixed'
                stop_loss_value = float(sl_fixed_match.group(1))
                stop_loss_fixed = stop_loss_value
    
    # Parse profit targets - check for ranges first (e.g., "first target 16.60-17")
    profit_targets = []
    target_ranges = []
    
    for range_match in CONDITIONAL_TARGET_RANGE_PATTERN.finditer(text):
        tier_str = range_match.group('tier') or 'first'
        tier_map = {'first': 1, '1st': 1, 'second': 2, '2nd': 2, 'third': 3, '3rd': 3, 'fourth': 4, '4th': 4}
        tier = tier_map.get(tier_str.lower(), 1)
        min_price = float(range_match.group('min_price'))
        max_price = float(range_match.group('max_price'))
        target_ranges.append({'tier': tier, 'min_price': min_price, 'max_price': max_price})
        # Use midpoint for backwards compatibility
        profit_targets.append((min_price + max_price) / 2)
    
    # If no ranges found, try regular target patterns
    if not target_ranges:
        multi_pt_match = CONDITIONAL_MULTI_PT_PATTERN.search(text)
        if multi_pt_match:
            for i in range(1, 5):
                pt_val = multi_pt_match.group(i)
                if pt_val:
                    profit_targets.append(float(pt_val))
        else:
            pt_match = CONDITIONAL_PT_PATTERN.search(text)
            if pt_match:
                profit_targets.append(float(pt_match.group(1)))
    
    # Parse position sizing
    position_size_pct = None
    fixed_qty = None
    size_mode = None
    
    pct_match = CONDITIONAL_POSITION_SIZE_PATTERN.search(text)
    if pct_match:
        position_size_pct = float(pct_match.group(1))
        size_mode = 'percent_account'
    else:
        # Try to find a standalone quantity (e.g., "100 shares")
        qty_match = re.search(r'(\d+)\s*(?:shares?|contracts?|cons?)', text, re.IGNORECASE)
        if qty_match:
            fixed_qty = int(qty_match.group(1))
            size_mode = 'fixed_qty'
    
    result = {
        'format': 'CONDITIONAL_ORDER',
        'is_conditional': True,
        'ticker': symbol,
        'symbol': symbol,
        'trigger_type': trigger_type,  # 'over' or 'under'
        'trigger_price': trigger_price,
        'stop_loss_type': stop_loss_type,
        'stop_loss_value': stop_loss_value,
        'stop_loss_fixed': stop_loss_fixed,  # Fixed price SL (for hybrid)
        'stop_loss_pct': stop_loss_pct,  # Percentage SL (for hybrid)
        'profit_targets': profit_targets,
        'target_ranges': target_ranges,  # List of {tier, min_price, max_price}
        'position_size_pct': position_size_pct,
        'fixed_qty': fixed_qty,
        'size_mode': size_mode,
        'asset': 'stock',
        'asset_type': 'stock',
        '_conditional_order': True,
        '_original_message': text,
    }
    
    # Log parsed conditional order
    if stop_loss_type == 'hybrid':
        sl_str = f"${stop_loss_fixed} or {stop_loss_pct}%"
    elif stop_loss_type == 'percent':
        sl_str = f"{stop_loss_value}%"
    elif stop_loss_value:
        sl_str = f"${stop_loss_value}"
    else:
        sl_str = "None"
    
    if target_ranges:
        pt_str = ', '.join([f"T{r['tier']}: ${r['min_price']}-{r['max_price']}" for r in target_ranges])
    elif profit_targets:
        pt_str = ', '.join([f"${pt}" for pt in profit_targets])
    else:
        pt_str = "None"
    
    size_str = f"{position_size_pct}% of account" if position_size_pct else f"{fixed_qty} shares" if fixed_qty else "channel default"
    
    print(f"[CONDITIONAL] ✓ Parsed: {symbol} {trigger_type} ${trigger_price}")
    print(f"[CONDITIONAL]   SL: {sl_str}, PT: {pt_str}, Size: {size_str}")
    
    return result


def format_conditional_for_display(parsed: Dict[str, Any]) -> str:
    """Format a parsed conditional order for display/logging."""
    symbol = parsed.get('symbol', '')
    trigger_type = parsed.get('trigger_type', 'over')
    trigger_price = parsed.get('trigger_price', 0)
    stop_loss_type = parsed.get('stop_loss_type')
    stop_loss_value = parsed.get('stop_loss_value')
    profit_targets = parsed.get('profit_targets', [])
    position_size_pct = parsed.get('position_size_pct')
    
    lines = [f"Conditional Order: {symbol} {trigger_type} ${trigger_price:.2f}"]
    
    if position_size_pct:
        lines.append(f"Position Size: {position_size_pct}% of account")
    
    if stop_loss_type and stop_loss_value:
        if stop_loss_type == 'percent':
            lines.append(f"Stop Loss: {stop_loss_value}%")
        else:
            lines.append(f"Stop Loss: ${stop_loss_value:.2f}")
    
    if profit_targets:
        pt_str = ', '.join([f"${pt:.2f}" for pt in profit_targets])
        lines.append(f"Profit Targets: {pt_str}")
    
    return '\n'.join(lines)


def parse_partial_exit_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse partial exit signals like "selling 80% MLTX", "selling 60%", "leaving 10%".
    
    Returns dict with:
        - action: 'PARTIAL_EXIT' or 'LEAVE_RUNNER'
        - exit_percent: percentage to sell (or leave for runner)
        - symbol: optional ticker symbol
    """
    # Check for "leaving X%" pattern first (leave runner)
    leave_match = LEAVING_RUNNER_PATTERN.search(text)
    if leave_match:
        leave_pct = float(leave_match.group('percent'))
        symbol = leave_match.group('symbol')
        sell_pct = 100.0 - leave_pct  # Sell everything except the runner
        
        result = {
            'format': 'PARTIAL_EXIT',
            'action': 'LEAVE_RUNNER',
            'exit_percent': sell_pct,
            'leave_percent': leave_pct,
            'symbol': symbol.upper() if symbol else None,
            '_original_message': text,
        }
        
        print(f"[PARTIAL EXIT] Leave runner: {leave_pct}% (selling {sell_pct}%)"
              f"{' of ' + symbol.upper() if symbol else ''}")
        return result
    
    # Check for regular partial exit patterns
    exit_match = PARTIAL_EXIT_PATTERN.search(text)
    if exit_match:
        percent = exit_match.group('percent')
        fraction = exit_match.group('fraction')
        symbol = exit_match.group('symbol')
        
        # Convert fractions to percentages
        if fraction:
            fraction_map = {'half': 50.0, 'quarter': 25.0, 'third': 33.33}
            exit_pct = fraction_map.get(fraction.lower(), 50.0)
        else:
            exit_pct = float(percent)
        
        result = {
            'format': 'PARTIAL_EXIT',
            'action': 'PARTIAL_EXIT',
            'exit_percent': exit_pct,
            'symbol': symbol.upper() if symbol else None,
            '_original_message': text,
        }
        
        print(f"[PARTIAL EXIT] Selling {exit_pct}%"
              f"{' of ' + symbol.upper() if symbol else ''}")
        return result
    
    return None


def parse_cancel_order_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse cancellation signals like "@Daytrades cancelling JTAI".
    
    Returns dict with symbol to cancel.
    """
    cancel_match = CANCEL_ORDER_PATTERN.search(text)
    if cancel_match:
        symbol = cancel_match.group('symbol').upper()
        
        result = {
            'format': 'CANCEL_ORDER',
            'action': 'CANCEL',
            'symbol': symbol,
            '_original_message': text,
        }
        
        print(f"[CANCEL] Order cancellation requested for {symbol}")
        return result
    
    return None


def parse_follow_up_update(text: str, context_symbol: str = None) -> Optional[Dict[str, Any]]:
    """
    Parse follow-up messages for SL/PT updates.
    
    These are messages that update an existing order's SL or PT.
    Examples: "SL now at 14.60", "PT raised to 17.50"
    
    Args:
        text: Message text
        context_symbol: Symbol from context (previous messages)
        
    Returns:
        Dict with update type and value, or None if not a follow-up update
    """
    updates = {}
    
    # Check for SL update
    sl_match = FOLLOW_UP_SL_PATTERN.search(text)
    if sl_match:
        price_str = sl_match.group('price')
        updates['stop_loss_update'] = float(price_str)
    
    # Check for PT update
    pt_match = FOLLOW_UP_PT_PATTERN.search(text)
    if pt_match:
        price_str = pt_match.group('price')
        updates['profit_target_update'] = float(price_str)
    
    if updates:
        result = {
            'format': 'FOLLOW_UP_UPDATE',
            'action': 'UPDATE',
            'symbol': context_symbol,
            **updates,
            '_original_message': text,
        }
        
        update_strs = []
        if 'stop_loss_update' in updates:
            update_strs.append(f"SL=${updates['stop_loss_update']}")
        if 'profit_target_update' in updates:
            update_strs.append(f"PT=${updates['profit_target_update']}")
        
        print(f"[FOLLOW-UP] Update detected: {', '.join(update_strs)}"
              f"{' for ' + context_symbol if context_symbol else ''}")
        return result
    
    return None


def is_partial_exit_signal(text: str) -> bool:
    """
    Check if text is a partial exit signal.
    
    IMPORTANT: This should NOT match standard STC signals like "STC 50% AAPL"
    to avoid intercepting normal exit signals. Only match natural language
    partial exit phrases like "selling 50%", "leaving 10%", etc.
    """
    text_upper = text.upper().strip()
    
    # Exclude standard STC signals - these should go through normal exit flow
    if text_upper.startswith('STC ') or text_upper.startswith('STC@'):
        return False
    
    # Exclude signals that look like option/stock trade formats
    if re.match(r'^(?:BTO|STC|BTC|STO)\s+', text_upper):
        return False
    
    return PARTIAL_EXIT_PATTERN.search(text) is not None or LEAVING_RUNNER_PATTERN.search(text) is not None


def is_cancel_order_signal(text: str) -> bool:
    """Check if text is a cancellation signal."""
    return CANCEL_ORDER_PATTERN.search(text) is not None


def parse_bracket_order_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse bracket order format signals with targets and stop loss.
    
    Example:
    BTO ENSC @ $2.02 (break)
    Targets: $2.1, $2.16, $2.22
    SL: $1.78
    
    Returns dict with parsed components or None if not a bracket order.
    """
    bto_match = BRACKET_BTO_PATTERN.search(text)
    if not bto_match:
        return None
    
    ticker = bto_match.group(1).upper()
    entry_price = float(bto_match.group(2))
    qualifier = bto_match.group(3) if bto_match.group(3) else None
    
    # Parse targets
    targets = []
    targets_match = BRACKET_TARGETS_PATTERN.search(text)
    if targets_match:
        targets_str = targets_match.group(1)
        for target in re.split(r'[,\s]+', targets_str):
            target_clean = re.sub(r'[^\d.]', '', target.strip())
            if target_clean:
                try:
                    targets.append(float(target_clean))
                except ValueError:
                    pass
    
    # Parse stop loss
    stop_loss = None
    sl_match = BRACKET_SL_PATTERN.search(text)
    if sl_match:
        stop_loss = float(sl_match.group(1))
    
    result = {
        'format': 'BRACKET_ORDER',
        'ticker': ticker,
        'symbol': ticker,
        'entry_price': entry_price,
        'price': entry_price,
        'entry_qualifier': qualifier,
        'profit_targets': targets,
        'stop_loss': stop_loss,
        'action': 'BTO',
        'asset': 'stock',
        'asset_type': 'stock',
        'qty': 1,
        '_qty_from_signal': False,
        '_bracket_order': True,
    }
    
    # Check if qualifier contains a position size percentage (e.g., "12.5%")
    if qualifier:
        pct_match = re.search(r'([\d.]+)%', qualifier)
        if pct_match:
            result['_position_size_pct'] = float(pct_match.group(1))
            print(f"[BRACKET ORDER] ✓ Parsed: {ticker} @ {entry_price}, {result['_position_size_pct']}% position, SL={stop_loss}, PTs={targets}")
            return result
    
    print(f"[BRACKET ORDER] ✓ Parsed: {ticker} @ {entry_price}, SL={stop_loss}, PTs={targets}")
    return result


def is_bracket_order_signal(text: str) -> bool:
    """Check if text is a bracket order format signal with targets/SL."""
    has_bto = BRACKET_BTO_PATTERN.search(text) is not None
    has_targets = BRACKET_TARGETS_PATTERN.search(text) is not None
    has_sl = BRACKET_SL_PATTERN.search(text) is not None
    return has_bto and (has_targets or has_sl)


def _parse_bullwinkle_expiry(expiry_text: str) -> str:
    """
    Parse Bullwinkle expiry text into MM/DD format.
    
    Supports:
    - "2/20", "12/12" (direct MM/DD)
    - "JAN/16", "JAN / 23" (month/day)
    - "NEXT WEEK" (next Friday)
    - "JAN 2027", "JAN / 2027", "MARCH 2026" (month year - use 3rd Friday)
    - "JAN", "MARCH" (just month - assume current year, 3rd Friday)
    """
    from datetime import datetime, timedelta
    import calendar
    
    if not expiry_text:
        # Default to today for 0DTE scalps
        return datetime.now().strftime("%m/%d")
    
    expiry_text = expiry_text.strip().upper()
    
    # Direct MM/DD format
    if re.match(r'^\d{1,2}/\d{1,2}$', expiry_text):
        parts = expiry_text.split('/')
        return f"{int(parts[0]):02d}/{int(parts[1]):02d}"
    
    # NEXT WEEK - find next Friday
    if 'NEXT' in expiry_text and 'WEEK' in expiry_text:
        today = datetime.now()
        days_until_friday = (4 - today.weekday()) % 7
        if days_until_friday == 0:
            days_until_friday = 7  # Next Friday, not today
        next_friday = today + timedelta(days=days_until_friday)
        return next_friday.strftime("%m/%d")
    
    # Month name mapping
    month_map = {
        'JAN': 1, 'JANUARY': 1, 'FEB': 2, 'FEBRUARY': 2,
        'MAR': 3, 'MARCH': 3, 'APR': 4, 'APRIL': 4,
        'MAY': 5, 'JUN': 6, 'JUNE': 6, 'JUL': 7, 'JULY': 7,
        'AUG': 8, 'AUGUST': 8, 'SEP': 9, 'SEPTEMBER': 9,
        'OCT': 10, 'OCTOBER': 10, 'NOV': 11, 'NOVEMBER': 11,
        'DEC': 12, 'DECEMBER': 12
    }
    
    # JAN/16, JAN / 23 format
    month_day_match = re.match(r'([A-Z]+)\s*/?\s*(\d{1,2})$', expiry_text)
    if month_day_match:
        month_str, day = month_day_match.groups()
        month = month_map.get(month_str)
        if month:
            return f"{month:02d}/{int(day):02d}"
    
    # JAN 2ND, DEC 15TH, MAR 3RD format (ordinal dates)
    ordinal_match = re.match(r'([A-Z]+)\s*(\d{1,2})(?:ST|ND|RD|TH)?$', expiry_text)
    if ordinal_match:
        month_str, day = ordinal_match.groups()
        month = month_map.get(month_str)
        if month:
            return f"{month:02d}/{int(day):02d}"
    
    # JAN 2027, MARCH 2026, JAN / 2027 format - use 3rd Friday of month
    month_year_match = re.match(r'([A-Z]+)\s*/?\s*(\d{4})$', expiry_text)
    if month_year_match:
        month_str, year = month_year_match.groups()
        month = month_map.get(month_str)
        if month:
            # Find 3rd Friday of that month
            year_int = int(year)
            first_day = datetime(year_int, month, 1)
            first_friday = first_day + timedelta(days=(4 - first_day.weekday()) % 7)
            third_friday = first_friday + timedelta(weeks=2)
            return third_friday.strftime("%m/%d")
    
    # Just month name (JAN, MARCH) - assume current/next occurrence, 3rd Friday
    for month_name, month_num in month_map.items():
        if month_name in expiry_text:
            today = datetime.now()
            year = today.year
            # If month already passed, use next year
            if month_num < today.month:
                year += 1
            first_day = datetime(year, month_num, 1)
            first_friday = first_day + timedelta(days=(4 - first_day.weekday()) % 7)
            third_friday = first_friday + timedelta(weeks=2)
            return third_friday.strftime("%m/%d")
    
    # Fallback to today
    return datetime.now().strftime("%m/%d")


def is_bullwinkle_signal(text: str) -> bool:
    """Check if text is a Bullwinkle format signal."""
    text_lower = text.lower()
    for indicator in BULLWINKLE_ENTRY_INDICATORS:
        if indicator.lower() in text_lower:
            return True
    for indicator in BULLWINKLE_EXIT_INDICATORS:
        if indicator.lower() in text_lower:
            return True
    return False


def is_zscalps_signal(text: str) -> bool:
    """Check if text is a Z-scalps format signal (SYMBOL | STRIKE C/P ...)."""
    clean_text = re.sub(r'@everyone|@here', '', text).strip()
    # Must have pipe format but NOT Bullwinkle emojis
    if '|' not in clean_text:
        return False
    if is_bullwinkle_signal(text):
        return False
    # Check for SYMBOL | pattern at start
    if ZSCALPS_ENTRY_PATTERN.search(clean_text):
        return True
    if ZSCALPS_ENTRY_PRICE_FIRST.search(clean_text):
        return True
    if ZSCALPS_EXIT_PATTERN.search(clean_text):
        return True
    if ZSCALPS_EXIT_PENDING.search(clean_text):
        return True
    return False


def parse_zscalps_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse Z-scalps format signals (simple pipe format without emojis).
    
    Supports:
    - TSLA | $460 C NEXT WEEK 7.15 @everyone (entry with expiry)
    - TSLA | $460 C 7.15 (entry, price at end)
    - TSLA | 7.45 OUT (exit)
    - TSLA | 7.35 PENDING ORDER TO EXIT HALF (partial exit)
    
    Returns structured dict with symbol, strike, opt_type, expiry, price, action.
    """
    if not is_zscalps_signal(text):
        return None
    
    clean_text = re.sub(r'@everyone|@here|✅|✔', '', text).strip()
    
    # Try exit patterns first
    
    # Exit: TSLA | 7.45 OUT
    match = ZSCALPS_EXIT_PATTERN.search(clean_text)
    if match:
        symbol, price = match.groups()
        return {
            'action': 'STC',
            'symbol': symbol.upper(),
            'price': float(price) if price else None,
            'qty': None,
            'is_exit': True,
            '_zscalps': True,
            '_needs_position_lookup': True,
        }
    
    # Partial exit: TSLA | 7.35 PENDING ORDER TO EXIT HALF
    match = ZSCALPS_EXIT_PENDING.search(clean_text)
    if match:
        symbol, price = match.groups()
        return {
            'action': 'STC',
            'symbol': symbol.upper(),
            'price': float(price) if price else None,
            'qty': None,  # HALF = partial
            'is_exit': True,
            '_zscalps': True,
            '_partial': True,
            '_needs_position_lookup': True,
        }
    
    # Entry: TSLA | $460 C NEXT WEEK 7.15 (expiry between C/P and price)
    match = ZSCALPS_ENTRY_PATTERN.search(clean_text)
    if match:
        symbol, strike, opt_type, expiry_text, price = match.groups()
        expiry = _parse_bullwinkle_expiry(expiry_text.strip())
        return {
            'action': 'BTO',
            'symbol': symbol.upper(),
            'strike': float(strike),
            'opt_type': opt_type.upper(),
            'expiry': expiry,
            'price': float(price),
            'qty': 1,
            '_zscalps': True,
        }
    
    # Entry variant: TSLA | $460 C 7.15 (price right after opt_type)
    match = ZSCALPS_ENTRY_PRICE_FIRST.search(clean_text)
    if match:
        symbol, strike, opt_type, price, expiry_text = match.groups()
        expiry = _parse_bullwinkle_expiry(expiry_text.strip() if expiry_text else '')
        return {
            'action': 'BTO',
            'symbol': symbol.upper(),
            'strike': float(strike),
            'opt_type': opt_type.upper(),
            'expiry': expiry,
            'price': float(price),
            'qty': 1,
            '_zscalps': True,
        }
    
    return None


def parse_bullwinkle_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse Bullwinkle format signals into structured dict.
    
    Supports multiple entry/exit formats including:
    - :green_alert: BTO 3 AMPX | $11 C .95 2/20
    - 🟢BTO $RKT | 21.2 C JAN/16 .56 5 cons
    - :green_alert: NVDA | $177.5 C 1.32
    - :green_alert: PLTR | 200 C NEXT WEEK .80
    - :SirenRed: STC ALL $AMPX ✅
    - :SirenRed: NVDA | 1.44 OUT ALL ✅
    
    Returns structured dict with symbol, strike, opt_type, expiry, price, qty, action.
    """
    if not is_bullwinkle_signal(text):
        return None
    
    # Clean text - remove @everyone and checkmark
    clean_text = re.sub(r'@everyone|✅|✔|@here', '', text).strip()
    
    # Try exit patterns first (more specific)
    
    # Exit Pattern 1: :SirenRed: STC ALL $AMPX
    match = BULLWINKLE_EXIT_STC_ALL.search(clean_text)
    if match:
        symbol = match.group(1).upper()
        return {
            'action': 'STC',
            'symbol': symbol,
            'price': None,  # Will need position lookup
            'qty': None,  # ALL = close full position
            'is_exit': True,
            '_bullwinkle': True,
            '_needs_position_lookup': True,
        }
    
    # Exit Pattern 2: :SirenRed: STC 4 RKT @ .75
    match = BULLWINKLE_EXIT_STC_QTY_PRICE.search(clean_text)
    if match:
        qty, symbol, price = match.groups()
        return {
            'action': 'STC',
            'symbol': symbol.upper(),
            'price': float(price) if price else None,
            'qty': int(qty),
            'is_exit': True,
            '_bullwinkle': True,
            '_needs_position_lookup': True,
        }
    
    # Exit Pattern 3: :SirenRed: STC $SYMBOL | .70 OUT
    match = BULLWINKLE_EXIT_STC_PIPE.search(clean_text)
    if match:
        symbol, price = match.groups()
        return {
            'action': 'STC',
            'symbol': symbol.upper(),
            'price': float(price) if price else None,
            'qty': None,
            'is_exit': True,
            '_bullwinkle': True,
            '_needs_position_lookup': True,
        }
    
    # Exit Pattern 4: :SirenRed: SYMBOL | PRICE OUT
    match = BULLWINKLE_EXIT_PIPE_PRICE.search(clean_text)
    if match:
        symbol, price = match.groups()
        return {
            'action': 'STC',
            'symbol': symbol.upper(),
            'price': float(price) if price else None,
            'qty': None,
            'is_exit': True,
            '_bullwinkle': True,
            '_needs_position_lookup': True,
        }
    
    # Exit Pattern 5: :SirenRed: SYMBOL | OUT @ PRICE
    match = BULLWINKLE_EXIT_OUT_AT.search(clean_text)
    if match:
        symbol, price = match.groups()
        return {
            'action': 'STC',
            'symbol': symbol.upper(),
            'price': float(price) if price else None,
            'qty': None,
            'is_exit': True,
            '_bullwinkle': True,
            '_needs_position_lookup': True,
        }
    
    # Exit Pattern 6: :SirenRed: PLTR 1.40OUT
    match = BULLWINKLE_EXIT_NO_SPACE.search(clean_text)
    if match:
        symbol, price = match.groups()
        return {
            'action': 'STC',
            'symbol': symbol.upper(),
            'price': float(price) if price else None,
            'qty': None,
            'is_exit': True,
            '_bullwinkle': True,
            '_needs_position_lookup': True,
        }
    
    # Exit Pattern 7: :SirenRed: STC $SYMBOL OUT ALL BUT 1 $PRICE
    match = BULLWINKLE_EXIT_COMPLEX.search(clean_text)
    if match:
        symbol, price = match.groups()
        return {
            'action': 'STC',
            'symbol': symbol.upper(),
            'price': float(price) if price else None,
            'qty': None,
            'is_exit': True,
            '_bullwinkle': True,
            '_needs_position_lookup': True,
        }
    
    # Now try entry patterns
    
    # Entry Pattern 1: :green_alert: BTO 3 AMPX | $11 C .95 2/20
    match = BULLWINKLE_ENTRY_BTO_QTY.search(clean_text)
    if match:
        qty, symbol, strike, opt_type, price, expiry_text = match.groups()
        expiry = _parse_bullwinkle_expiry(expiry_text)
        return {
            'asset': 'option',
            'action': 'BTO',
            'symbol': symbol.upper(),
            'strike': float(strike),
            'opt_type': opt_type.upper(),
            'expiry': expiry,
            'price': float(price),
            'qty': int(qty),
            '_qty_from_signal': True,
            '_bullwinkle': True,
        }
    
    # Entry Pattern 2: 🟢BTO $RKT | 21.2 C JAN/16 .56 5 cons
    match = BULLWINKLE_ENTRY_BTO_QTY_END.search(clean_text)
    if match:
        symbol, strike, opt_type, expiry_text, price, qty = match.groups()
        expiry = _parse_bullwinkle_expiry(expiry_text)
        return {
            'asset': 'option',
            'action': 'BTO',
            'symbol': symbol.upper(),
            'strike': float(strike),
            'opt_type': opt_type.upper(),
            'expiry': expiry,
            'price': float(price),
            'qty': int(qty),
            '_qty_from_signal': True,
            '_bullwinkle': True,
        }
    
    # Entry Pattern 4 (before 3): :green_alert: SYMBOL | STRIKE C EXPIRY PRICE (price at end)
    match = BULLWINKLE_ENTRY_PRICE_END.search(clean_text)
    if match:
        symbol, strike, opt_type, expiry_text, price = match.groups()
        expiry = _parse_bullwinkle_expiry(expiry_text)
        return {
            'asset': 'option',
            'action': 'BTO',
            'symbol': symbol.upper(),
            'strike': float(strike),
            'opt_type': opt_type.upper(),
            'expiry': expiry,
            'price': float(price),
            'qty': None,  # Will use defaults
            '_qty_from_signal': False,
            '_bullwinkle': True,
        }
    
    # Entry Pattern 3: :green_alert: SYMBOL | $STRIKE C PRICE (standard - price after C/P)
    match = BULLWINKLE_ENTRY_STANDARD.search(clean_text)
    if match:
        symbol, strike, opt_type, price, expiry_text = match.groups()
        expiry = _parse_bullwinkle_expiry(expiry_text)
        return {
            'asset': 'option',
            'action': 'BTO',
            'symbol': symbol.upper(),
            'strike': float(strike),
            'opt_type': opt_type.upper(),
            'expiry': expiry,
            'price': float(price),
            'qty': None,  # Will use defaults
            '_qty_from_signal': False,
            '_bullwinkle': True,
        }
    
    # Entry Pattern 5: :green_alert: SYMBOL | $STRIKE PRICE EXPIRY (no C/P, assume call)
    # Example: :green_alert: TSLA | $492.5 10.10 JAN 2ND
    match = BULLWINKLE_ENTRY_NO_CP.search(clean_text)
    if match:
        symbol, strike, price, expiry_text = match.groups()
        expiry = _parse_bullwinkle_expiry(expiry_text)
        return {
            'asset': 'option',
            'action': 'BTO',
            'symbol': symbol.upper(),
            'strike': float(strike),
            'opt_type': 'C',  # Default to call when not specified
            'expiry': expiry,
            'price': float(price),
            'qty': None,
            '_qty_from_signal': False,
            '_bullwinkle': True,
        }
    
    return None


def strip_bullwinkle_emojis(text: str) -> str:
    """
    Strip emojis and Discord custom emotes from Bullwinkle signals.
    
    Removes:
    - Unicode emojis: 🟢, 🔴, ✅, etc.
    - Discord custom emotes: :green_alert:, :SirenRed:, :greenalert:, etc.
    - Discord animated emotes: <a:name:id> or <:name:id>
    
    Returns cleaned text suitable for webhook forwarding.
    """
    import re
    
    # Remove Discord custom animated emotes <a:name:id> and static <:name:id>
    clean = re.sub(r'<a?:[a-zA-Z0-9_]+:\d+>', '', text)
    
    # Remove Discord colon-coded emotes (:name: or :name_name:)
    clean = re.sub(r':[a-zA-Z0-9_]+:', '', clean)
    
    # Remove common Unicode emojis used in trading signals
    emoji_pattern = re.compile(
        "["
        "\U0001F7E2"  # 🟢 green circle
        "\U0001F534"  # 🔴 red circle
        "\U00002705"  # ✅ check mark
        "\U0001F6A8"  # 🚨 siren
        "\U0001F4C8"  # 📈 chart
        "\U0001F4CC"  # 📌 pin
        "\U0001F4B0"  # 💰 money bag
        "\U000026D4"  # ⛔ no entry
        "\U0001F525"  # 🔥 fire
        "\U0001F680"  # 🚀 rocket
        "\U0001F4A1"  # 💡 light bulb
        "\U0001F4AF"  # 💯 hundred
        "\U00002757"  # ❗ exclamation
        "\U00002B06"  # ⬆️ up arrow
        "\U00002B07"  # ⬇️ down arrow
        "]+",
        flags=re.UNICODE
    )
    clean = emoji_pattern.sub('', clean)
    
    # Clean up extra whitespace
    clean = re.sub(r'\s+', ' ', clean).strip()
    
    return clean


def format_bullwinkle_for_webhook(parsed: dict) -> str:
    """
    Format a parsed Bullwinkle signal for clean webhook forwarding.
    
    Entry: BTO NVDA 177.5C 12/29 @ 1.32
    Exit: STC NVDA @ 1.44
    
    No emojis, clean format.
    """
    action = parsed.get('action', 'BTO')
    symbol = parsed.get('symbol', 'UNKNOWN')
    price = parsed.get('price', 0)
    
    if parsed.get('is_exit'):
        # Exit signal
        return f"STC {symbol} @ {price}"
    else:
        # Entry signal
        strike = parsed.get('strike', '')
        opt_type = parsed.get('opt_type', 'C')
        expiry = parsed.get('expiry', '')
        qty = parsed.get('qty')
        
        msg = f"BTO"
        if qty:
            msg += f" {qty}"
        msg += f" {symbol} {strike}{opt_type}"
        if expiry:
            msg += f" {expiry}"
        msg += f" @ {price}"
        
        return msg


def normalize_bullwinkle_format(text: str) -> str:
    """
    Convert Bullwinkle scalp format to standard BTO/STC format.
    
    Entry: :green_alert: NVDA | $177.5 C 1.32 → BTO NVDA 177.5 C @ 1.32
    Exit: :SirenRed: NVDA | 1.44 OUT ALL ✅ → STC NVDA @ 1.44
    
    Note: Exit signals don't include strike/expiry, so they need position lookup.
    """
    # Check for exit signal first (more specific pattern)
    exit_match = BULLWINKLE_EXIT_PATTERN.search(text)
    if exit_match:
        symbol, price = exit_match.groups()
        # Return as stock-style STC - the caller will need to find the matching position
        normalized = f"STC {symbol.upper()} @ {price}"
        print(f"[BULLWINKLE] Converted exit: '{text[:60]}' → '{normalized}'")
        return normalized
    
    # Check for entry signal
    entry_match = BULLWINKLE_ENTRY_PATTERN.search(text)
    if entry_match:
        symbol, strike, opt_type, price = entry_match.groups()
        # Get current expiry (assume 0DTE or next trading day)
        from datetime import datetime, timedelta
        now = datetime.now()
        # Default to today's date for 0DTE scalps
        expiry = now.strftime("%m/%d")
        
        normalized = f"BTO {symbol.upper()} {strike} {opt_type.upper()} {expiry} @ {price}"
        print(f"[BULLWINKLE] Converted entry: '{text[:60]}' → '{normalized}'")
        return normalized
    
    # Not Bullwinkle format, return original
    return text


INDIA_SL_PATTERN = re.compile(r'SL\s*[₹]?([\d.]+)', re.IGNORECASE)
INDIA_TGT_PATTERN = re.compile(r'(?:TGT|TARGET|TP)\s*[₹]?([\d.\-]+)', re.IGNORECASE)
INDIA_CONDITIONAL_PATTERN = re.compile(r'\b(ABOVE|BELOW)\b', re.IGNORECASE)


def parse_india_option_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse an Indian option trading signal from text.
    
    Supported formats:
    - "BUY NIFTY 24000 CE @ 145"
    - "SELL BANKNIFTY 49500 PE @ 220"
    - "NIFTY 24100 CE BUY @ 130"
    - "BUY 2 LOT NIFTY 24000 CE @ 145"
    - "BUY NIFTY 24000 CE 28 DEC @ 145"
    - "BUY NIFTY 25900 CE ABOVE ₹190 SL ₹180 TGT ₹202-220-240"
    
    Args:
        text: Raw message text to parse
        
    Returns:
        Dictionary with signal details or None if not matched
    """
    from datetime import datetime
    
    text_clean = text.strip()
    
    text_clean = re.sub(r'\*\*(.+?)\*\*', r'\1', text_clean, flags=re.DOTALL)
    text_clean = re.sub(r'\*(.+?)\*', r'\1', text_clean, flags=re.DOTALL)
    text_clean = re.sub(r'__(.+?)__', r'\1', text_clean, flags=re.DOTALL)
    text_clean = re.sub(r'_(.+?)_', r'\1', text_clean, flags=re.DOTALL)
    text_clean = re.sub(r'~~(.+?)~~', r'\1', text_clean, flags=re.DOTALL)
    text_clean = re.sub(r'`(.+?)`', r'\1', text_clean, flags=re.DOTALL)
    text_clean = re.sub(r'```(.+?)```', r'\1', text_clean, flags=re.DOTALL)
    
    text_clean = re.sub(r'[\r\n]+', ' ', text_clean)
    text_clean = re.sub(r'\s+', ' ', text_clean).strip()
    
    for i, pattern in enumerate(INDIA_PATTERNS):
        regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        m = regex.search(text_clean)
        
        if m:
            groups = m.groups()
            
            if pattern == INDIA_OPT_PATTERN_ABOVE:
                direction, symbol, strike, opt_type, price_str = groups[0], groups[1], groups[2], groups[3], groups[4]
                expiry_str = None
                qty = None
            elif pattern == INDIA_OPT_PATTERN_EXPIRY_FIRST:
                direction, qty_str, symbol, expiry_str, strike, opt_type = groups[0], groups[1], groups[2], groups[3], groups[4], groups[5]
                price_str = groups[6] if len(groups) > 6 else None
                qty = int(qty_str) if qty_str else None
            elif pattern == INDIA_OPT_PATTERN_NO_PRICE:
                direction, qty_str, symbol, strike, opt_type, expiry_str = groups[0], groups[1], groups[2], groups[3], groups[4], groups[5]
                price_str = None
                qty = int(qty_str) if qty_str else None
            elif i == 3:
                direction, symbol, strike, opt_type, price_str = groups[0], groups[1], groups[2], groups[3], groups[4]
                expiry_str = None
                qty = None
            elif i == 4:
                symbol, strike, opt_type, direction, price_str = groups[0], groups[1], groups[2], groups[3], groups[4]
                expiry_str = None
                qty = None
            elif i == 5:
                direction, symbol, strike, opt_type, expiry_str, price_str = groups[0], groups[1], groups[2], groups[3], groups[4], groups[5]
                qty = None
            elif i == 6:
                direction, qty_str, symbol, strike, opt_type, price_str = groups[0], groups[1], groups[2], groups[3], groups[4], groups[5]
                qty = int(qty_str) if qty_str else None
                expiry_str = None
            elif i == 7:
                direction, qty_str, symbol, strike, opt_type, price_str = groups[0], groups[1], groups[2], groups[3], groups[4], groups[5]
                qty = int(qty_str) if qty_str else None
                expiry_str = None
            else:
                continue
            
            symbol = symbol.upper()
            direction = direction.upper()
            opt_type = opt_type.upper()
            
            action = 'BTO' if direction == 'BUY' else 'STC'
            call_put = 'C' if opt_type == 'CE' else 'P'
            
            if expiry_str:
                expiry = _parse_india_expiry(expiry_str)
            else:
                expiry = _get_next_nse_expiry(symbol)
            
            lot_size = NSE_LOT_SIZES.get(symbol, 1)
            quantity = (qty * lot_size) if qty else lot_size
            
            try:
                price = float(price_str)
            except (ValueError, TypeError):
                price = None
            
            stop_loss = None
            sl_match = INDIA_SL_PATTERN.search(text_clean)
            if sl_match:
                try:
                    stop_loss = float(sl_match.group(1))
                except (ValueError, TypeError):
                    pass
            
            profit_targets = []
            tgt_match = INDIA_TGT_PATTERN.search(text_clean)
            if tgt_match:
                tgt_str = tgt_match.group(1)
                for tgt in re.split(r'[-,\s]+', tgt_str):
                    tgt_clean = tgt.strip()
                    if tgt_clean:
                        try:
                            profit_targets.append(float(tgt_clean))
                        except (ValueError, TypeError):
                            pass
            
            is_conditional = bool(INDIA_CONDITIONAL_PATTERN.search(text_clean))
            conditional_match = INDIA_CONDITIONAL_PATTERN.search(text_clean)
            trigger_type = conditional_match.group(1).lower() if conditional_match else None
            
            result = {
                'asset': 'option',
                'action': action,
                'direction': action,
                'symbol': symbol,
                'strike': float(strike),
                'opt_type': call_put,
                'call_put': call_put,
                'expiry': expiry,
                'price': price,
                'qty': quantity,
                '_qty_from_signal': qty is not None,
                'lots': qty or 1,
                'lot_size': lot_size,
                'asset_type': 'option',
                'market': 'INDIA',
                'exchange_segment': 'NSE_FNO',
                'is_market_order': price is None,
                'original_format': 'INDIA',
                'stop_loss': stop_loss,
                'profit_targets': profit_targets if profit_targets else None,
                '_conditional_order': is_conditional,
                'trigger_price': price if is_conditional else None,
                'trigger_type': 'over' if trigger_type == 'above' else 'under' if trigger_type == 'below' else None,
            }
            
            sl_str = f" SL=₹{stop_loss}" if stop_loss else ""
            tgt_str = f" TGT={profit_targets}" if profit_targets else ""
            cond_str = f" [CONDITIONAL: {trigger_type} ₹{price}]" if is_conditional else ""
            print(f"[INDIA] ✓ Parsed: {action} {quantity} {symbol} {strike}{opt_type} {expiry} @ ₹{price}{sl_str}{tgt_str}{cond_str}")
            return result
    
    return None


def parse_india_stock_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse an Indian stock trading signal from text.
    
    Supported formats:
    - "BUY RELIANCE @ 2500"
    - "SELL TCS @ 3800"
    
    Args:
        text: Raw message text to parse
        
    Returns:
        Dictionary with signal details or None if not matched
    """
    text_clean = text.strip()
    text_clean = re.sub(r'\*\*(.+?)\*\*', r'\1', text_clean, flags=re.DOTALL)
    text_clean = re.sub(r'\*(.+?)\*', r'\1', text_clean, flags=re.DOTALL)
    text_clean = re.sub(r'__(.+?)__', r'\1', text_clean, flags=re.DOTALL)
    text_clean = re.sub(r'_(.+?)_', r'\1', text_clean, flags=re.DOTALL)
    
    text_clean = re.sub(r'[\r\n]+', ' ', text_clean)
    text_clean = re.sub(r'\s+', ' ', text_clean).strip()
    
    regex = re.compile(INDIA_STK_PATTERN, re.IGNORECASE | re.MULTILINE)
    m = regex.search(text_clean)
    
    if not m:
        return None
    
    direction, symbol, price_str = m.groups()
    
    symbol = symbol.upper()
    direction = direction.upper()
    action = 'BTO' if direction == 'BUY' else 'STC'
    
    try:
        price = float(price_str)
    except (ValueError, TypeError):
        price = None
    
    result = {
        'asset': 'stock',
        'action': action,
        'direction': action,
        'symbol': symbol,
        'price': price,
        'qty': 1,
        '_qty_from_signal': False,
        'asset_type': 'stock',
        'market': 'INDIA',
        'exchange_segment': 'NSE_EQ',
        'is_market_order': price is None,
        'original_format': 'INDIA',
    }
    
    print(f"[INDIA] ✓ Parsed stock: {action} {symbol} @ {price}")
    return result


def _parse_india_expiry(expiry_str: str) -> str:
    """
    Parse Indian date format (DD MMM YYYY) to MM/DD format.
    
    Examples:
    - "28 DEC 2025" -> "12/28"
    - "28 DEC" -> "12/28"
    - "28DEC25" -> "12/28"
    """
    from datetime import datetime
    import re
    
    if not expiry_str:
        return _get_next_nse_expiry('NIFTY')
    
    expiry_clean = expiry_str.upper().strip()
    
    match = re.match(r'(\d{1,2})\s*(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s*(\d{2,4})?', expiry_clean)
    
    if match:
        day = int(match.group(1))
        month = INDIA_MONTH_MAP.get(match.group(2), 1)
        return f"{month:02d}/{day:02d}"
    
    return _get_next_nse_expiry('NIFTY')


def _get_next_nse_expiry(symbol: str) -> str:
    """
    Get the next expiry date for NSE F&O.
    
    NSE Expiry Schedule (effective September 2025):
    - NIFTY: Weekly (Tuesday) - only index with weekly options
    - BANKNIFTY/FINNIFTY/MIDCPNIFTY: Monthly only (last Tuesday)
    - Stock options: Monthly (last Tuesday)
    """
    from datetime import datetime, timedelta
    
    now = datetime.now()
    
    weekly_symbols = ['NIFTY']
    
    if symbol.upper() in weekly_symbols:
        days_ahead = 1 - now.weekday()
        if days_ahead < 0:
            days_ahead += 7
        elif days_ahead == 0 and now.hour >= 15:
            days_ahead = 7
        
        next_tuesday = now + timedelta(days=days_ahead)
        return next_tuesday.strftime("%m/%d")
    else:
        year = now.year
        month = now.month
        
        last_day = (datetime(year, month % 12 + 1, 1) - timedelta(days=1)).day if month < 12 else 31
        last_tuesday = None
        
        for day in range(last_day, 0, -1):
            test_date = datetime(year, month, day)
            if test_date.weekday() == 1:
                last_tuesday = test_date
                break
        
        if last_tuesday and last_tuesday <= now:
            if month == 12:
                month = 1
                year += 1
            else:
                month += 1
            last_day = (datetime(year, month % 12 + 1, 1) - timedelta(days=1)).day if month < 12 else 31
            for day in range(last_day, 0, -1):
                test_date = datetime(year, month, day)
                if test_date.weekday() == 1:
                    last_tuesday = test_date
                    break
        
        return last_tuesday.strftime("%m/%d") if last_tuesday else now.strftime("%m/%d")


def is_india_signal(text: str) -> bool:
    """
    Check if the text appears to be an Indian market signal.
    
    Looks for:
    - CE/PE option types
    - BUY/SELL (not BTO/STC)
    - Indian symbols like NIFTY, BANKNIFTY
    - ₹ symbol
    """
    text_upper = text.upper()
    
    if 'CE' in text_upper or 'PE' in text_upper:
        return True
    
    if ('BUY ' in text_upper or 'SELL ' in text_upper) and ('BTO ' not in text_upper and 'STC ' not in text_upper):
        india_symbols = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'SENSEX', 'BANKEX', 'RELIANCE', 'TCS', 'INFY', 'HDFCBANK']
        for sym in india_symbols:
            if sym in text_upper:
                return True
    
    if '₹' in text:
        return True
    
    return False


_option_regex = None
_stock_regex = None


def _get_option_regex():
    """Get or create the option regex pattern."""
    global _option_regex
    if _option_regex is None:
        pattern = None
        try:
            from gui_app.database import get_discord_settings
            discord_settings = get_discord_settings()
            db_pattern = discord_settings.get('option_pattern', '').strip()
            if db_pattern:
                pattern = db_pattern
        except Exception:
            pass
        
        if pattern is None:
            try:
                import configparser
                cfg = configparser.ConfigParser()
                cfg.read('config.ini')
                cfg.read('config.ini.example')
                pattern = cfg.get('signals', 'pattern', fallback=FLEXIBLE_OPT_PATTERN)
            except Exception:
                pattern = FLEXIBLE_OPT_PATTERN
        
        _option_regex = create_option_regex(pattern)
    
    return _option_regex


def _get_stock_regex():
    """Get or create the stock regex pattern."""
    global _stock_regex
    if _stock_regex is None:
        pattern = None
        try:
            from gui_app.database import get_discord_settings
            discord_settings = get_discord_settings()
            db_pattern = discord_settings.get('stock_pattern', '').strip()
            if db_pattern:
                pattern = db_pattern
        except Exception:
            pass
        
        if pattern is None:
            try:
                import configparser
                cfg = configparser.ConfigParser()
                cfg.read('config.ini')
                cfg.read('config.ini.example')
                pattern = cfg.get('signals', 'stock_pattern', fallback=DEFAULT_STK_PATTERN)
            except Exception:
                pattern = DEFAULT_STK_PATTERN
        
        _stock_regex = create_stock_regex(pattern)
    
    return _stock_regex


def get_default_option_pattern() -> str:
    """Get the default option signal pattern."""
    return FLEXIBLE_OPT_PATTERN


def get_default_stock_pattern() -> str:
    """Get the default stock signal pattern."""
    return DEFAULT_STK_PATTERN


def _get_max_position_size() -> float:
    """Get the max position size from settings."""
    try:
        from src.core import get_trading_settings
        settings = get_trading_settings()
        return settings.get('max_position_size', 1000)
    except ImportError:
        return 1000


def parse_option_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse an option trading signal from text.
    
    Expected format: BTO/STC [QTY] SYMBOL STRIKE C/P MM/DD @ PRICE
    Example: "BTO 5 AAPL 150 C 12/20 @ 2.50"
    Example: "STC TSLA 200 P 01/15 @ m" (market order)
    
    Args:
        text: Raw message text to parse
        
    Returns:
        Dictionary with signal details or None if not matched
    """
    regex = _get_option_regex()
    m = regex.search(text.strip())
    
    if not m:
        print(f"[SIGNAL] ❌ Option pattern NOT matched: '{text.strip()[:80]}'")
        print(f"[SIGNAL]    Expected format: BTO/STC QTY SYMBOL STRIKE C/P MM/DD @ PRICE")
        return None
    
    direction, qty_str, symbol, strike, opt_type, expiry, price_str = m.groups()
    
    is_market_order = price_str.lower() == 'm'
    if is_market_order:
        price = None
        print(f"[SIGNAL] Market order detected for {symbol} {strike}{opt_type} {expiry}")
    else:
        price = float(price_str)
    
    qty_from_signal = False
    if qty_str is None:
        # Don't calculate qty here - let the handler apply tiered defaults
        # (channel default → global default → max_position_size if enabled → 1)
        qty = None
        print(f"[SIGNAL] No quantity specified - handler will apply tiered defaults")
    else:
        qty = int(qty_str)
        qty_from_signal = True
    
    return {
        "asset": "option",
        "action": direction.upper(),
        "qty": qty,
        "symbol": symbol.upper(),
        "strike": float(strike),
        "opt_type": opt_type.upper(),
        "expiry": expiry,
        "price": price,
        "is_market_order": is_market_order,
        "_qty_from_signal": qty_from_signal
    }


def parse_stock_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse a stock trading signal from text.
    
    Expected format: BTO/STC [QTY] SYMBOL @ PRICE
    Example: "BTO 100 AAPL @ 150.00"
    Example: "STC TSLA @ m" (market order)
    
    Args:
        text: Raw message text to parse
        
    Returns:
        Dictionary with signal details or None if not matched
    """
    regex = _get_stock_regex()
    m = regex.search(text.strip())
    
    if not m:
        return None
    
    direction, qty_str, symbol, price_str = m.groups()
    
    is_market_order = price_str.lower() == 'm'
    if is_market_order:
        price = None
        print(f"[SIGNAL] Market order detected for {symbol}")
    else:
        price = float(price_str)
    
    qty_from_signal = False
    if qty_str is None:
        # Don't calculate qty here - let the handler apply tiered defaults
        qty = None
        print(f"[SIGNAL] No quantity specified - handler will apply tiered defaults")
    else:
        qty = int(qty_str)
        qty_from_signal = True
    
    return {
        "asset": "stock",
        "action": direction.upper(),
        "qty": qty,
        "symbol": symbol.upper(),
        "price": price,
        "is_market_order": is_market_order,
        "_qty_from_signal": qty_from_signal
    }


class SignalParser:
    """
    Signal parser with customizable patterns and settings.
    Use this for more control over parsing behavior.
    """
    
    def __init__(
        self,
        option_pattern: Optional[str] = None,
        stock_pattern: Optional[str] = None,
        max_position_size: float = 1000,
        ignore_case: bool = True
    ):
        """
        Initialize the signal parser.
        
        Args:
            option_pattern: Custom option regex pattern
            stock_pattern: Custom stock regex pattern
            max_position_size: Max dollar amount per position
            ignore_case: Whether to ignore case in matching
        """
        self.option_regex = create_option_regex(option_pattern, ignore_case)
        self.stock_regex = create_stock_regex(stock_pattern, ignore_case)
        self.max_position_size = max_position_size
    
    def parse(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Parse a trading signal from text.
        Tries option format first, then stock format.
        
        Args:
            text: Raw message text to parse
            
        Returns:
            Dictionary with signal details or None if not matched
        """
        result = self.parse_option(text)
        if result:
            return result
        
        return self.parse_stock(text)
    
    def parse_option(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse an option signal."""
        m = self.option_regex.search(text.strip())
        if not m:
            return None
        
        direction, qty_str, symbol, strike, opt_type, expiry, price_str = m.groups()
        
        is_market_order = price_str.lower() == 'm'
        price = None if is_market_order else float(price_str)
        
        if qty_str is None:
            if is_market_order:
                qty = 1
            else:
                actual_cost = price * 100
                if actual_cost <= 0:
                    return None
                qty = max(1, int(self.max_position_size / actual_cost))
        else:
            qty = int(qty_str)
        
        return {
            "asset": "option",
            "action": direction.upper(),
            "qty": qty,
            "symbol": symbol.upper(),
            "strike": float(strike),
            "opt_type": opt_type.upper(),
            "expiry": expiry,
            "price": price,
            "is_market_order": is_market_order
        }
    
    def parse_stock(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse a stock signal."""
        m = self.stock_regex.search(text.strip())
        if not m:
            return None
        
        direction, qty_str, symbol, price_str = m.groups()
        
        is_market_order = price_str.lower() == 'm'
        price = None if is_market_order else float(price_str)
        
        if qty_str is None:
            if is_market_order:
                qty = 1
            elif price and price > 0:
                qty = max(1, int(self.max_position_size / price))
            else:
                return None
        else:
            qty = int(qty_str)
        
        return {
            "asset": "stock",
            "action": direction.upper(),
            "qty": qty,
            "symbol": symbol.upper(),
            "price": price,
            "is_market_order": is_market_order
        }


def reload_patterns():
    """Force reload of regex patterns from database/config."""
    global _option_regex, _stock_regex
    _option_regex = None
    _stock_regex = None
