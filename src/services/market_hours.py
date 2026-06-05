"""
Market Hours Utility
====================
Provides market status checking for risk management decisions.
"""

from datetime import datetime, time, timedelta
from typing import Tuple, Optional
import pytz


US_EASTERN = pytz.timezone('US/Eastern')

MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
PRE_MARKET_OPEN = time(4, 0)
AFTER_HOURS_CLOSE = time(20, 0)

US_MARKET_HOLIDAYS_2025 = {
    datetime(2025, 1, 1),   # New Year's Day
    datetime(2025, 1, 20),  # MLK Day
    datetime(2025, 2, 17),  # Presidents Day
    datetime(2025, 4, 18),  # Good Friday
    datetime(2025, 5, 26),  # Memorial Day
    datetime(2025, 6, 19),  # Juneteenth
    datetime(2025, 7, 4),   # Independence Day
    datetime(2025, 9, 1),   # Labor Day
    datetime(2025, 11, 27), # Thanksgiving
    datetime(2025, 12, 25), # Christmas
}

US_MARKET_HOLIDAYS_2026 = {
    datetime(2026, 1, 1),   # New Year's Day
    datetime(2026, 1, 19),  # MLK Day
    datetime(2026, 2, 16),  # Presidents Day
    datetime(2026, 4, 3),   # Good Friday
    datetime(2026, 5, 25),  # Memorial Day
    datetime(2026, 6, 19),  # Juneteenth
    datetime(2026, 7, 3),   # Independence Day (observed)
    datetime(2026, 9, 7),   # Labor Day
    datetime(2026, 11, 26), # Thanksgiving
    datetime(2026, 12, 25), # Christmas
}


def get_eastern_now() -> datetime:
    """Get current time in US Eastern timezone."""
    return datetime.now(US_EASTERN)


def is_market_holiday(dt: Optional[datetime] = None) -> bool:
    """Check if the given date is a US market holiday."""
    if dt is None:
        dt = get_eastern_now()
    
    date_only = datetime(dt.year, dt.month, dt.day)
    
    if dt.year == 2025:
        return date_only in US_MARKET_HOLIDAYS_2025
    elif dt.year == 2026:
        return date_only in US_MARKET_HOLIDAYS_2026
    
    return False


def is_weekend(dt: Optional[datetime] = None) -> bool:
    """Check if the given date is a weekend."""
    if dt is None:
        dt = get_eastern_now()
    return dt.weekday() >= 5


def is_regular_market_hours(dt: Optional[datetime] = None) -> bool:
    """
    Check if currently within regular market hours (9:30 AM - 4:00 PM ET).
    Returns False on weekends and holidays.
    """
    if dt is None:
        dt = get_eastern_now()
    
    if is_weekend(dt) or is_market_holiday(dt):
        return False
    
    current_time = dt.time()
    return MARKET_OPEN <= current_time < MARKET_CLOSE


def is_extended_hours(dt: Optional[datetime] = None) -> bool:
    """
    Check if currently within extended hours (pre-market or after-hours).
    Pre-market: 4:00 AM - 9:30 AM ET
    After-hours: 4:00 PM - 8:00 PM ET
    """
    if dt is None:
        dt = get_eastern_now()
    
    if is_weekend(dt) or is_market_holiday(dt):
        return False
    
    current_time = dt.time()
    
    pre_market = PRE_MARKET_OPEN <= current_time < MARKET_OPEN
    after_hours = MARKET_CLOSE <= current_time < AFTER_HOURS_CLOSE
    
    return pre_market or after_hours


def is_options_trading_hours(dt: Optional[datetime] = None) -> bool:
    """
    Check if options are tradeable.
    Options typically only trade during regular market hours.
    """
    return is_regular_market_hours(dt)


def get_market_status(dt: Optional[datetime] = None) -> Tuple[str, bool]:
    """
    Get detailed market status.
    
    Returns:
        Tuple of (status_string, is_risk_monitoring_allowed)
    
    Status strings:
        - 'regular' - Regular market hours, risk monitoring allowed
        - 'pre_market' - Pre-market, limited risk monitoring
        - 'after_hours' - After hours, limited risk monitoring
        - 'closed' - Market closed, no risk monitoring
        - 'weekend' - Weekend, no risk monitoring
        - 'holiday' - Holiday, no risk monitoring
    """
    if dt is None:
        dt = get_eastern_now()
    
    if is_weekend(dt):
        return ('weekend', False)
    
    if is_market_holiday(dt):
        return ('holiday', False)
    
    current_time = dt.time()
    
    if MARKET_OPEN <= current_time < MARKET_CLOSE:
        return ('regular', True)
    
    if PRE_MARKET_OPEN <= current_time < MARKET_OPEN:
        return ('pre_market', False)
    
    if MARKET_CLOSE <= current_time < AFTER_HOURS_CLOSE:
        return ('after_hours', False)
    
    return ('closed', False)


def get_next_market_open() -> datetime:
    """Get the next market open time."""
    now = get_eastern_now()
    
    next_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    
    if now.time() >= MARKET_OPEN:
        next_open += timedelta(days=1)
    
    while is_weekend(next_open) or is_market_holiday(next_open):
        next_open += timedelta(days=1)
    
    return next_open


def time_until_market_open() -> timedelta:
    """Get time remaining until market opens."""
    return get_next_market_open() - get_eastern_now()


def format_market_status() -> str:
    """Get a human-readable market status string."""
    status, _ = get_market_status()
    
    status_messages = {
        'regular': 'Market Open',
        'pre_market': 'Pre-Market',
        'after_hours': 'After Hours',
        'closed': 'Market Closed',
        'weekend': 'Weekend - Market Closed',
        'holiday': 'Holiday - Market Closed',
    }
    
    return status_messages.get(status, 'Unknown')
