"""
Signals module - Signal parsing and validation for trading signals.
Contains regex patterns, parsers, and validators for options and stocks.
"""

from .parser import (
    parse_option_signal,
    parse_stock_signal,
    SignalParser,
    get_default_option_pattern,
    get_default_stock_pattern,
)
from .patterns import (
    FLEXIBLE_OPT_PATTERN,
    DEFAULT_STK_PATTERN,
    create_option_regex,
    create_stock_regex,
)
from .validator import (
    validate_signal,
    is_valid_symbol,
    is_valid_strike,
    is_valid_expiry,
    is_valid_action,
)

__all__ = [
    'parse_option_signal',
    'parse_stock_signal',
    'SignalParser',
    'get_default_option_pattern',
    'get_default_stock_pattern',
    'FLEXIBLE_OPT_PATTERN',
    'DEFAULT_STK_PATTERN',
    'create_option_regex',
    'create_stock_regex',
    'validate_signal',
    'is_valid_symbol',
    'is_valid_strike',
    'is_valid_expiry',
    'is_valid_action',
]
