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

# ============ JAKE SIGNAL PATTERNS ============
# Jake's channel format: **SYMBOL** $STRIKEc|p EXPIRY @lim PRICE
# Examples:
#   **MSTR** $188c 19DEC2025 @lim3.0
#   **COIN** $330p 27JUN @lim2.07
#   **IWM** $244p 09OCT2025 @ lim0.10-0.20
#   **MSTR** $325c 17OCT @ lim1.90

# Entry pattern: **SYMBOL** $STRIKEc|p EXPIRY @lim PRICE
JAKE_ENTRY_PATTERN = re.compile(
    r'\*\*([A-Z]+)\*\*\s+\$?([\d.]+)\s*([cp])\s+'  # **SYMBOL** $STRIKE c|p
    r'(\d{1,2}[A-Z]{3}(?:\d{2,4})?|\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s*'  # Expiry: 19DEC2025, 12DEC, 27JUN, 1/17
    r'@\s*lim\s*([\d.]+)(?:\s*-\s*[\d.]+)?',  # @lim PRICE (optional range)
    re.IGNORECASE
)

# Exit/Update pattern: **SYMBOL** +XX% @limPRICE (partial exit indicator)
JAKE_EXIT_PATTERN = re.compile(
    r'\*\*([A-Z]+)\*\*\s+\+(\d+(?:\.\d+)?)\s*%\s*@\s*lim\s*([\d.]+)',
    re.IGNORECASE
)

# Levels pattern: __$**SYMBOL** Levels__ (followed by PT lines)
JAKE_LEVELS_PATTERN = re.compile(
    r'__\$?\*?\*?([A-Z]+)\*?\*?\s*Levels?__',
    re.IGNORECASE
)

# ============ JAKE/JOINT-CHALLENGE EXTENDED PATTERNS ============
# Entry with quantity prefix: +2 **SNOW** @lim0.11 (stock) or +1 **$RGTI** $26c @lim0.80 (option)
# Stock format: +QTY **SYMBOL** @limPRICE
JAKE_QTY_STOCK_ENTRY = re.compile(
    r'\+(\d+)\s+(?:\$?\*{0,2})([A-Z]+)(?:\*{0,2})\s+@\s*lim\s*([\d.]+)',
    re.IGNORECASE
)

# Option with quantity: +QTY $SYMBOL $STRIKEc/p EXPIRY @limPRICE
# Example: +2 $**BBAI** $8c 16JAN2026 @lim0.37
JAKE_QTY_OPTION_ENTRY = re.compile(
    r'\+(\d+)\s+\$?\*{0,2}([A-Z]+)\*{0,2}\s+\$?([\d.]+)\s*([cp])\s*'
    r'(?:(\d{1,2}[A-Z]{3}(?:\d{2,4})?|\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s*)?'  # Optional expiry
    r'@\s*lim\s*([\d.]+)',
    re.IGNORECASE
)

# Full exit: All out of **SYMBOL** @limPRICE for +XX% or -$XX
JAKE_ALL_OUT_PATTERN = re.compile(
    r'(?:all\s+)?out\s+of\s+\$?\*{0,2}([A-Z]+)\*{0,2}\s+@\s*lim\s*([\d.]+)',
    re.IGNORECASE
)

# Exit with percentage gain header: ## $SYMBOL +XX% @limPRICE or **SYMBOL** +XX% @limPRICE
JAKE_PCT_EXIT_EXTENDED = re.compile(
    r'(?:#+\s*)?\$?\*{0,2}([A-Z]+)\*{0,2}\s+\+(\d+(?:\.\d+)?)\s*%\s*@\s*lim\s*([\d.]+)',
    re.IGNORECASE
)

# Sell order initiated: Sell order @limPRICE or Can place sell order @limPRICE
JAKE_SELL_ORDER_PATTERN = re.compile(
    r'(?:sell\s+order|can\s+place\s+sell\s+order)\s+(?:already\s+)?(?:initiated\s+)?@\s*(?:here\s+)?@?\s*lim\s*([\d.]+)',
    re.IGNORECASE
)

# Position update header pattern (for context, not execution)
JAKE_POSITION_UPDATE_HEADER = re.compile(
    r'(?:current\s+)?positions?|active\s+positions?|portfolio',
    re.IGNORECASE
)

# ============ ORDER EXECUTED BROKER CONFIRMATION PATTERNS ============
# Format: "Order Executed\nBought 5 Single SNDK 1/9/2026 360 CALL @4.80 [Buy Open]"
# Format: "Order Executed\nSold -1 Single SNDK 1/9/2026 360 CALL @9.40 [Sell Close]"
# Examples:
#   Order Executed
#   Bought 5 Single SNDK 1/9/2026 360 CALL @4.80 [Buy Open]
#   Sold -1 Single SNDK 1/9/2026 360 CALL @9.70 [Sell Close]

# Buy pattern: Bought QTY Single SYMBOL EXPIRY STRIKE CALL/PUT @PRICE [Buy Open]
ORDER_EXECUTED_BUY_PATTERN = re.compile(
    r'(?:Order\s+Executed\s*)?\s*Bought\s+(\d+)\s+Single\s+([A-Z]+)\s+'
    r'(\d{1,2}/\d{1,2}/\d{2,4})\s+'  # Expiry: 1/9/2026
    r'([\d.]+)\s+'  # Strike: 360
    r'(CALL|PUT)\s+'  # Option type
    r'@\s*([\d.]+)',  # Price
    re.IGNORECASE
)

# Sell pattern: Sold -QTY Single SYMBOL EXPIRY STRIKE CALL/PUT @PRICE [Sell Close]
ORDER_EXECUTED_SELL_PATTERN = re.compile(
    r'(?:Order\s+Executed\s*)?\s*Sold\s+(-?\d+)\s+Single\s+([A-Z]+)\s+'
    r'(\d{1,2}/\d{1,2}/\d{2,4})\s+'  # Expiry
    r'([\d.]+)\s+'  # Strike
    r'(CALL|PUT)\s+'  # Option type
    r'@\s*([\d.]+)',  # Price
    re.IGNORECASE
)

# ============ BISHOP FORMAT PATTERNS ============
# Format (in Discord embeds):
#   **Option:** TSLA 437.50 C 1/9
#   **Entry:** 2.48
# Examples:
#   **Option:** HOOD 140 C 2/20\n**Entry:** 3.35-3.36
#   **Option:** ABNB 150 C 2/26\n**Entry:** 3.30
#   **Option:** TSLA 437.50 P 1/16\n**Entry:** 3.05-3.10

BISHOP_ENTRY_PATTERN = re.compile(
    r'\*\*Option:\*\*\s*([A-Z]+)\s+([\d.]+)\s*([CP])\s+(\d{1,2}/\d{1,2})'  # **Option:** SYMBOL STRIKE C/P MM/DD
    r'.*?\*\*Entry:\*\*\s*([\d.]+)(?:\s*-\s*([\d.]+))?',  # **Entry:** PRICE or PRICE-PRICE
    re.IGNORECASE | re.DOTALL
)

# Bishop exit patterns (narrative style)
# Examples: "Out of SNOW calls swing for -35%", "Out of AMZN for -27%", "Out of ABNB at 2.50"
# Pattern 1: "out of SYMBOL calls/puts" (with calls/puts)
# Pattern 2: "out of SYMBOL at/for/around PRICE/%" (with price or percentage)
# Pattern 3: "out of these/the/rest SYMBOL calls/puts" (with article before symbol)
BISHOP_EXIT_PATTERN = re.compile(
    r'(?:out\s+of|all\s+out\s+of?|exiting?)\s+'
    r'(?:the\s+rest\s+of\s+|these\s+)?'  # Optional article/modifier
    r'([A-Z]{1,5})\s+'  # Symbol (1-5 uppercase letters) followed by space
    r'(?:calls?|puts?|(?:at|for|around|swing)\s+[-\d.]+%?)',  # REQUIRED: calls/puts OR price/pct to distinguish from casual text
    re.IGNORECASE
)

# Bishop trimming exit pattern (structured, in embed title)
# Examples:
#   Trimming CAT 640 C 1/16 @$11.25
#   Trimming JNJ 220 C 2/20 @$3.37
#   Trimming TSLA 437.50 P 1/16 @$3.60
#   Trimming TSLA 387.5 P 2/6 | **Value:** @3.60  (new format with Value separator)
#   Trimming TSLA 405 C 2/6\n**Value:** @2.70  (embed format: title + description on separate lines)
BISHOP_TRIMMING_PATTERN = re.compile(
    r'Trimming\s+([A-Z]+)\s+([\d.]+)\s*([CP])\s+(\d{1,2}/\d{1,2})(?:\s*[\|\n]\s*[*]{0,2}Value:?[*]{0,2})?\s*@\s*[\$]?([\d.]+)',
    re.IGNORECASE | re.DOTALL
)

#   Trimming MRK 115 C 2/20 @$190%!!
#   Trimming SPY 600 P 2/14 @$250%
#   Trimming TSLA 387.5 P 2/6 | **Value:** @250%  (new format with Value separator)
#   Trimming TSLA 405 C 2/6\n**Value:** @250%  (embed format: title + description on separate lines)
BISHOP_TRIMMING_PERCENT_PATTERN = re.compile(
    r'Trimming\s+([A-Z]+)\s+([\d.]+)\s*([CP])\s+(\d{1,2}/\d{1,2})(?:\s*[\|\n]\s*[*]{0,2}Value:?[*]{0,2})?\s*@\s*[\$]?([\d.]+)\s*%',
    re.IGNORECASE | re.DOTALL
)

# ============ EVAPANDA FORMAT PATTERNS ============
# Format: BTO SYMBOL MM/DD/YY STRIKE+C/P @ PRICE (notes)
# Examples:
#   BTO AVGO 01/30/26 400C @ 1.42 (risky swing)
#   STC SPY 01/15/26 700C @ 1.12 (all out on runner)
#   BTO NFLX 08/26/2026 130c @ 1.83 (Long Swing)

EVAPANDA_PATTERN = re.compile(
    r'(BTO|STC)\s+([A-Z]+)\s+'
    r'(\d{1,2}/\d{1,2}/\d{2,4})\s+'  # Expiry: MM/DD/YY or MM/DD/YYYY
    r'([\d.]+)\s*([CP])\s*'  # Strike + type: 400C
    r'@\s*([\d.]+)',  # Price
    re.IGNORECASE
)

# ============ TOON FORMAT PATTERNS ============
# Format: BTO/STC SYMBOL MM/DD STRIKE+C/P @ m [partial]
# Examples:
#   BTO spy 1/16 692p @ m gonna swing these
#   BTO spy 1/23 692p @ m
#   stc spy 1/16 692p @ m partial
#   stc spy 1/16 692p @ m (full close)

# Entry: BTO SYMBOL MM/DD STRIKE+C/P @ m
TOON_ENTRY_PATTERN = re.compile(
    r'\b(BTO)\s+([A-Z]+)\s+'        # BTO SYMBOL
    r'(\d{1,2}/\d{1,2})\s+'         # Expiry: MM/DD (1/16)
    r'([\d.]+)\s*([CP])\s*'         # Strike + type: 692p
    r'@\s*m',                       # @ m (at market)
    re.IGNORECASE
)

# Exit: STC SYMBOL MM/DD STRIKE+C/P @ m [partial]
TOON_EXIT_PATTERN = re.compile(
    r'\b(STC)\s+([A-Z]+)\s+'        # STC SYMBOL
    r'(\d{1,2}/\d{1,2})\s+'         # Expiry: MM/DD
    r'([\d.]+)\s*([CP])\s*'         # Strike + type
    r'@\s*m'                        # @ m (at market)
    r'(?:\s+(partial))?',           # Optional "partial"
    re.IGNORECASE
)

# ============ CONDITIONAL ORDER PATTERNS ============
# These patterns detect price-triggered conditional orders
# Examples:
#   "LVRO over 1.30 SL 10% profit target 1.43"
#   "AAPL over 250 10% of ACCOUNT PT 260 SL 240"
#   "SPY under 680 stop loss 2% take profit 675"

# Main conditional trigger pattern: SYMBOL over/under PRICE or PRICE-RANGE
# Supports: "FRSX over 2.35" or "FRSX over 2.35-2.4" (uses first price as trigger)
# Also handles common typos: ocer, ober, ovwe, ovre, ovr, abve, abov
CONDITIONAL_TRIGGER_PATTERN = re.compile(
    r'(?:^|\s)\$?([A-Z]{1,5})\s+(?:over|ocer|ocver|ober|ovwe|ovre|ovr|iver|above|abve|abov)\s*\$?([\d.]+)(?:\s*[-–—to]+\s*\$?[\d.]+)?',
    re.IGNORECASE
)

CONDITIONAL_TRIGGER_UNDER_PATTERN = re.compile(
    r'(?:^|\s)\$?([A-Z]{1,5})\s+(?:under|below)\s*\$?([\d.]+)(?:\s*[-–—to]+\s*\$?[\d.]+)?',
    re.IGNORECASE
)

# Alternative format: BELOW/UNDER SYMBOL PRICE (e.g., "BELOW QQQ 607")
CONDITIONAL_TRIGGER_UNDER_ALT_PATTERN = re.compile(
    r'(?:^|\s)(?:under|below)\s+\$?([A-Z]{1,5})\s+\$?([\d.]+)',
    re.IGNORECASE
)

# Alternative format: ABOVE/OVER SYMBOL PRICE (e.g., "ABOVE SPY 500")
CONDITIONAL_TRIGGER_ABOVE_ALT_PATTERN = re.compile(
    r'(?:^|\s)(?:over|ocer|ocver|ober|ovwe|ovre|ovr|above|abve|abov)\s+\$?([A-Z]{1,5})\s+\$?([\d.]+)',
    re.IGNORECASE
)

# Stop loss patterns for conditional orders
CONDITIONAL_SL_PERCENT_PATTERN = re.compile(
    r'(?:SL|stop\s*loss|stop)\s*[:\s]*(\d+(?:\.\d+)?)(?:\s*[-–—]\s*\d+(?:\.\d+)?)?\s*%',
    re.IGNORECASE
)

CONDITIONAL_SL_FIXED_PATTERN = re.compile(
    r'(?:SL|stop\s*loss|stop)\s*[:\s@]*\$?(\d+(?:\.\d+)?)(?!\s*[-–—]?\s*\d*\s*%)(?!\.\d)',
    re.IGNORECASE
)

# Profit target patterns for conditional orders
# PT percentage: "target 10%", "first target 10%", "PT 5%"
CONDITIONAL_PT_PERCENT_PATTERN = re.compile(
    r'(?:(?:first|second|third|fourth|1st|2nd|3rd|4th)\s+)?'
    r'(?:PT|profit\s*target|target|take\s*profit|TP)\s*[:\s@]*'
    r'(\d+(?:\.\d+)?)\s*%'
    r'(?:\s*\(\s*\$?([\d.]+)\s*\))?',
    re.IGNORECASE
)

CONDITIONAL_PT_PATTERN = re.compile(
    r'(?:PT|profit\s*target|target|take\s*profit|TP)\s*[:\s@]*\$?([\d.]+)(?!\s*%)',
    re.IGNORECASE
)

# Multiple profit targets: PT 1.43, 1.50, 1.60
CONDITIONAL_MULTI_PT_PATTERN = re.compile(
    r'(?:PT|profit\s*target|targets?|take\s*profit|TP)\s*[:\s]*\$?([\d.]+)(?!\s*%)(?:[,\s]+\$?([\d.]+))?(?:[,\s]+\$?([\d.]+))?(?:[,\s]+\$?([\d.]+))?',
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

# Partial exit patterns: "selling 80% MLTX", "selling 60%", "selling half", "selling 80% here EVTV"
# Phoenix formats: "selling 80% here", "selling 10% more CRVS", "selling 80% here IBRX"
PARTIAL_EXIT_PATTERN = re.compile(
    r'(?:(?:will\s+be\s+)?selling|sold|trimm?(?:ing|ed)?|taking\s+(?:off|profit))\s+'
    r'(?:'
    r'(?P<percent>\d+(?:\.\d+)?)\s*%|'
    r'(?P<fraction>half|quarter|third)|'
    r'(?P<pre_symbol>[A-Z]{1,5})\s+(?P<pre_percent>\d+(?:\.\d+)?)\s*%'
    r')\s*'
    r'(?:of\s+)?(?:my\s+)?(?:position\s+)?(?:in\s+)?'
    r'(?:(?:here|now|on|more)\s*)*'
    r'(?:\$?(?P<symbol>(?!here|now|on|more)[A-Z]{1,5})(?![a-z]))?',
    re.IGNORECASE
)

# Full exit without percentage: "out of POLA", "out PAVM", "stopped out MIGI", "out of SEGG with remaining shares"
FULL_EXIT_PATTERN = re.compile(
    r'(?:out\s+(?:of\s+)?|exiting|exited|closed?\s+out|closing|stopped?\s+out\s+(?:of\s+)?)\s*'
    r'(?:\$?(?P<symbol>[A-Z]{1,5}))'
    r'(?:\s+with\s+(?:the\s+)?remain(?:ing|der))?',
    re.IGNORECASE
)

# Trimming pattern: "trimming GITS", "trimmed PAVM" (implies ~50% partial exit)
TRIMMING_PATTERN = re.compile(
    r'trimm?(?:ing|ed)\s+\$?(?P<symbol>(?!here|now|on|more|all|the|my|of)[A-Z]{1,5})(?![a-z])',
    re.IGNORECASE
)

# Direct sell without percentage: "selling XTLB", "im selling RXT", "I'm selling CRVS" (implies 100% exit)
# Must exclude reserved words: here, now, on, more, all, half, quarter, third
DIRECT_SELL_PATTERN = re.compile(
    r'(?:(?:i\'?m|i\s+am|we\'?re|we\s+are|just)\s+)?'  # Optional natural language prefix
    r'(?:selling|sold)\s+(?!\d)'  # Must NOT be followed by a number (that's partial exit)
    r'(?:\$?(?P<symbol>(?!here|now|on|more|all|half|quarter|third|rest)[A-Z]{1,5}))(?:\s|$)',
    re.IGNORECASE
)

# Leaving runner pattern: "leaving 10%", "leaving 20% MLTX", "leaving 10% here GITS"
# Must exclude reserved words: here, now, on, more
LEAVING_RUNNER_PATTERN = re.compile(
    r'(?:leaving|keeping)\s+(?P<percent>\d+(?:\.\d+)?)\s*%\s*'
    r'(?:of\s+)?(?:my\s+)?(?:position\s+)?(?:in\s+)?'
    r'(?:(?:here|now|on|more)\s*)*'  # Location/continuation words (consume but don't capture)
    r'(?:\$?(?P<symbol>(?!here|now|on|more)[A-Z]{1,5})(?![a-z]))?',
    re.IGNORECASE
)

# Phoenix "next target" pattern: "next target 3.95-4", "next target 2.70"
# This indicates profit target update for active positions
PHOENIX_NEXT_TARGET_PATTERN = re.compile(
    r'(?:next\s+)?(?:target|tgt|pt)\s*[:\s]*\$?(?P<price1>[\d.]+)(?:\s*[-–—to]+\s*\$?(?P<price2>[\d.]+))?',
    re.IGNORECASE
)

# Phoenix "hit SL" / "stopped out" pattern: indicates stop loss triggered
PHOENIX_STOP_HIT_PATTERN = re.compile(
    r'(?:hit\s+(?:my\s+)?(?:SL|stop\s*loss)|stopped?\s+out|stop(?:ped)?\s+hit)',
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
# Detects delayed SL/PT updates: "SL now at 14.60", "PT raised to 17.50", "moving my SL to 1.88"
FOLLOW_UP_SL_PATTERN = re.compile(
    r'(?:(?:moving|mov(?:e|ed)?)\s+(?:my\s+)?)?'
    r'(?:SL|stop\s*loss|stop)\s*'
    r'(?:(?:for|on)\s+\$?[A-Z]{1,5}\s+)?'
    r'(?:now\s+)?(?:at|to|moved?\s+to|raised?\s+to|lowered?\s+to|changed?\s+to|updated?\s+to|set\s+(?:at|to))?\s*'
    r'[:\s@]*\$?(?P<price>[\d.]+)(?!\s*%)',
    re.IGNORECASE
)

# Percentage SL pattern for Phoenix-style: "SL 10%", "stop loss 5%", "moving my SL to 11%"
FOLLOW_UP_SL_PERCENT_PATTERN = re.compile(
    r'(?:(?:moving|mov(?:e|ed)?)\s+(?:my\s+)?)?'  # Optional "moving my" prefix
    r'(?:SL|stop\s*loss|stop)\s*'
    r'(?:now\s+)?(?:at|to|moved?\s+to|raised?\s+to|lowered?\s+to|changed?\s+to|updated?\s+to|set\s+(?:at|to))?\s*'
    r'[:\s@]*(?P<pct>[\d.]+)\s*%',
    re.IGNORECASE
)

FOLLOW_UP_PT_PATTERN = re.compile(
    r'(?:(?:first|second|third|next)\s+)?'
    r'(?:PT|targets?|profits?|profit\s*target|take\s*profit|TP)\s*'
    r'(?:(?:for|of|on)\s+\$?[A-Z]{1,5}\s+)?'
    r'(?:now\s+)?(?:at|moved?\s+to|raised?\s+to|changed?\s+to|updated?\s+to|set\s+(?:at|to)|hit[,\s])?\s*'
    r'(?:\$?[A-Z]{1,5}\s+)?'
    r'[:\s@]*\$?(?P<price>[\d.]+)',
    re.IGNORECASE
)

FOLLOW_UP_PT_RANGE_PATTERN = re.compile(
    r'(?:(?:first|second|third|next)\s+)?'
    r'(?:targets?|profits?|PT|profit\s*target|take\s*profit|TP)\s*'
    r'(?:(?:for|of|on)\s+\$?[A-Z]{1,5}\s+)?'
    r'(?:\$?[A-Z]{1,5}\s+)?'
    r'[:\s@]*\$?(?P<price1>[\d.]+)\s*[-–—to]+\s*\$?(?P<price2>[\d.]+)',
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
    r'(?:📌\s*)?(?:Ticker|Symbol):\s*\*{0,2}\$?([A-Z]+)\*{0,2}',
    re.IGNORECASE
)
TRADE_IDEA_ENTRY_PATTERN = re.compile(
    r'(?:💰\s*)?(?:Entry|Price):\s*\$?([\d.]+)',
    re.IGNORECASE
)
TRADE_IDEA_LEVELS_PATTERN = re.compile(
    r'(?:📈\s*)?(?:Levels|Targets|PTs?):\s*([\d.\s\-\+]+)',
    re.IGNORECASE
)
TRADE_IDEA_SL_PATTERN = re.compile(
    r'(?:⛔\s*)?(?:SL|Stop\s*Loss|Stop|Support):\s*(?:below\s+)?\$?([\d.]+|B/?E|BREAKEVEN|BREAK\s*EVEN)',
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
# Unicode characters: \u200e=LRM, \u200f=RLM, \u202a-\u202e=embedding controls, \u200b=ZWSP
JACOB_ENTERED_PATTERN = re.compile(
    r'ENTERED[\s\u200b-\u200f\u202a-\u202e]+(LONG|SHORT)[\s\u200b-\u200f\u202a-\u202e]*:[\s\u200b-\u200f\u202a-\u202e]*\$?([A-Z]{1,5})',
    re.IGNORECASE
)
JACOB_ENTRY_PATTERN = re.compile(
    r'ENTRY[\s\u200b-\u200f\u202a-\u202e]*:[\s\u200b-\u200f\u202a-\u202e]*\$?([\d.]+)',
    re.IGNORECASE
)
JACOB_SL_PATTERN = re.compile(
    r'S\.?L\.?[\s\u200b-\u200f\u202a-\u202e]*:[\s\u200b-\u200f\u202a-\u202e]*\$?([\d.]+)',
    re.IGNORECASE
)
JACOB_TARGET_PATTERN = re.compile(
    r'(?:1st[\s\u200b-\u200f\u202a-\u202e]+)?Target[\s\u200b-\u200f\u202a-\u202e]*:[\s\u200b-\u200f\u202a-\u202e]*\$?([\d]+\.{1,2}\d+)',
    re.IGNORECASE
)


def tokenize_levels_with_strikethrough(levels_str: str) -> list:
    """
    Tokenize price levels with strikethrough awareness.
    
    Handles both formats:
    - Per-target: ~~1.21~~ - ~~1.24~~ - 1.28
    - Range: ~~1.21 - 1.24 - 1.28~~ (all inside one strikethrough)
    - Mixed: ~~1.21 - 1.24~~ - 1.28 (first two hit, last pending)
    
    Returns list of tuples: [(price_value, is_hit), ...]
    """
    tokens = []
    inside_strike = False
    current_token = ""
    token_was_struck = False  # Track if current token was inside strikethrough
    i = 0
    
    while i < len(levels_str):
        # Check for ~~ marker
        if i < len(levels_str) - 1 and levels_str[i:i+2] == '~~':
            if inside_strike:
                # Closing ~~ - mark current token as struck before toggling
                token_was_struck = True
            inside_strike = not inside_strike
            if inside_strike:
                # Opening ~~ - mark current token as struck
                token_was_struck = True
            i += 2
            continue
        
        char = levels_str[i]
        
        # Check for separator (hyphen or dash)
        if char in '-–':
            # Emit current token if we have one
            clean = re.sub(r'[^\d.]', '', current_token)
            if clean:
                try:
                    # Token is hit if it was ever inside strikethrough
                    tokens.append((float(clean), token_was_struck or inside_strike))
                except ValueError:
                    pass
            current_token = ""
            token_was_struck = inside_strike  # Reset for next token, inheriting current state
            i += 1
            continue
        
        current_token += char
        i += 1
    
    # Process final token
    if current_token.strip():
        clean = re.sub(r'[^\d.]', '', current_token)
        if clean:
            try:
                tokens.append((float(clean), token_was_struck or inside_strike))
            except ValueError:
                pass
    
    return tokens


def parse_trade_idea(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse TRADE IDEA / SCALP IDEA / SWING IDEA format signals (C1apped style).
    
    Example:
    | TRADE IDEA
    📌 Ticker: TRIB
    💰 Entry: 1.36
    📈 Levels: 1.45 - 1.49 - 1.56 - 1.65 - 1.77+
    ⛔ SL: 1.22
    
    Also matches:
    | SCALP IDEA  (same format, different title)
    | SWING IDEA  (same format, different title)
    NOTE with Ticker:/Entry:/Price: fields
    
    Strikethrough Detection:
    When levels have ~~strikethrough~~ (e.g., "Levels: ~~1.26~~ - 1.29"), 
    those are marked as hit_levels indicating partial exits occurred.
    Supports both per-target (~~1.21~~ - ~~1.24~~) and range (~~1.21 - 1.24~~) formats.
    
    Returns dict with parsed components or None if not a TRADE IDEA.
    """
    text_upper = text.upper()
    is_clapped_format = any(kw in text_upper for kw in ('TRADE IDEA', 'SCALP IDEA', 'SWING IDEA'))
    has_structured_fields = TRADE_IDEA_TICKER_PATTERN.search(text) and TRADE_IDEA_ENTRY_PATTERN.search(text)
    if not is_clapped_format and not has_structured_fields:
        return None
    
    ticker_match = TRADE_IDEA_TICKER_PATTERN.search(text)
    entry_match = TRADE_IDEA_ENTRY_PATTERN.search(text)
    sl_match = TRADE_IDEA_SL_PATTERN.search(text)
    
    if not ticker_match or not entry_match:
        return None
    
    ticker = ticker_match.group(1).upper()
    entry_price = float(entry_match.group(1))
    
    stop_loss = None
    is_breakeven = False
    if sl_match:
        sl_value = sl_match.group(1).strip().upper()
        if sl_value in ('B/E', 'BE', 'BREAKEVEN', 'BREAK EVEN'):
            stop_loss = entry_price
            is_breakeven = True
        else:
            try:
                stop_loss = float(sl_value)
            except ValueError:
                stop_loss = None
    
    profit_targets = []
    hit_levels = []
    pending_levels = []
    
    levels_line_match = re.search(r'(?:📈\s*)?(?:Levels|Targets|PTs?):\s*(.+?)(?:\n|$)', text, re.IGNORECASE)
    if levels_line_match:
        levels_str = levels_line_match.group(1)
        levels_str = re.sub(r'[+\s]+$', '', levels_str)
        
        # Use state-machine tokenizer for proper strikethrough handling
        # Handles both ~~1.21~~ - ~~1.24~~ and ~~1.21 - 1.24~~ formats
        tokens = tokenize_levels_with_strikethrough(levels_str)
        
        for level_value, is_hit in tokens:
            profit_targets.append(level_value)
            if is_hit:
                hit_levels.append(level_value)
            else:
                pending_levels.append(level_value)
    
    is_exit = 'all out' in text.lower() or 'closed' in text.lower() or 'exited' in text.lower()
    is_update = len(hit_levels) > 0 or is_breakeven or 'raised' in text.lower() or 'moved' in text.lower()
    
    signal_type = 'exit' if is_exit else ('update' if is_update else 'entry')
    
    result = {
        'format': 'TRADE_IDEA',
        'ticker': ticker,
        'symbol': ticker,
        'entry_price': entry_price,
        'price': entry_price,
        'stop_loss': stop_loss,
        'is_breakeven': is_breakeven,
        'profit_targets': profit_targets,
        'hit_levels': hit_levels,
        'pending_levels': pending_levels,
        'is_exit': is_exit,
        'is_update': is_update,
        'signal_type': signal_type,
        'action': 'STC' if is_exit else 'BTO',
        'asset': 'stock',
        'asset_type': 'stock',
        'qty': 1,
        '_qty_from_signal': False,
        '_trade_idea': True,
    }
    
    be_str = " [B/E]" if is_breakeven else ""
    hit_str = f", HIT={hit_levels}" if hit_levels else ""
    pending_str = f", PENDING={pending_levels}" if pending_levels else ""
    type_str = f" [{signal_type.upper()}]" if signal_type != 'entry' else ""
    print(f"[TRADE IDEA] ✓ Parsed: {ticker} @ {entry_price}, SL={stop_loss}{be_str}{hit_str}{pending_str}{type_str}")
    return result


def is_trade_idea_signal(text: str) -> bool:
    """Check if text is a TRADE IDEA / SCALP IDEA / SWING IDEA format signal."""
    text_upper = text.upper()
    has_idea_keyword = any(kw in text_upper for kw in ('TRADE IDEA', 'SCALP IDEA', 'SWING IDEA'))
    has_structured_fields = (
        TRADE_IDEA_TICKER_PATTERN.search(text) is not None and
        TRADE_IDEA_ENTRY_PATTERN.search(text) is not None
    )
    return (has_idea_keyword or has_structured_fields) and (
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
        try:
            target_val = target_match.group(1).replace('..', '.')
            targets.append(float(target_val))
        except (ValueError, TypeError):
            pass
    
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


def is_conditional_order_signal(text: str, require_sl_pt: bool = False) -> bool:
    """
    Check if text is a conditional order signal (price-triggered entry).
    
    Conditional orders require explicit 'over/above' or 'under/below' keywords
    to distinguish from regular BTO/STC signals.
    
    Args:
        text: The message text to check
        require_sl_pt: If True, requires SL/PT/position size in the same message.
                       If False (default), allows trigger-only signals.
                       Trigger-only signals can receive SL/PT from follow-up messages.
    """
    text_upper = text.upper()
    
    # Exclude "Watching XXX over Y.Y" patterns - these are watchlist alerts, not trade signals
    # Examples: "Watching TEAD over 0.70 @Daytrades", "Watching BNAI over 30.00 @Daytrades"
    # Also handles Jacob typos: "Watching. ISPC over", "WatchingVCIG OVEE", "Watching RIME pver"
    # and variants: "Also watching over 40.00", "Still watching UGRO over 12.00"
    if re.search(r'\bWATCHING\s+[A-Z]+\s+OVER\b', text_upper):
        return False
    stripped = re.sub(r'[.\s\u200b-\u200f\u202a-\u202e]+', ' ', text_upper).strip()
    if re.search(r'(?:^|\b)WATCHING\s*[A-Z]{1,5}\b', stripped):
        return False
    if re.search(r'\bWATCHING\b', text_upper) and re.search(r'\bOV(?:ER|EE|ER)\b', text_upper):
        return False
    
    # Exclude protrader/quick-swing structured format — these have their own parser in the format registry
    # Examples: "Ticker: CYCN\nEntry range: 3.2-3.30\nSL below 3.00"
    #           "Ticker: $TDOC\nEntry: range (4.90-4.50)\nTarget: (...)\nStop loss: Below 3.50"
    if re.search(r'Ticker\s*:\s*\$?[A-Z]{1,5}\s*\n\s*Ent(?:e|r)y\s+range\s*:', text, re.IGNORECASE):
        return False
    if re.search(r'Ticker\s*:\s*\$?[A-Z]{1,5}\s*\n\s*Entry\s*:\s*range\s*\(', text, re.IGNORECASE):
        return False
    
    # Exclude market commentary patterns — these describe price action, not trade signals
    # Examples: "$QQQ under 605 can see $602.50 can see $599"
    #           "SPY over 500 looking for 510 next"
    #           "AAPL above 180 could go to 185"
    commentary_patterns = [
        r'\b(?:CAN\s+SEE|LOOKING\s+(?:FOR|AT)|COULD\s+(?:GO|SEE|HEAD|MOVE)|HEADING\s+(?:TO|TOWARD)|EXPECTING|EYEING|MIGHT\s+(?:GO|SEE|HIT|REACH)|SHOULD\s+(?:GO|SEE|HIT|REACH))\b',
        r'\b(?:WATCH(?:ING)?|MONITOR(?:ING)?)\s+(?:FOR|THE|THIS|IT)\b',
    ]
    for pat in commentary_patterns:
        if re.search(pat, text_upper):
            print(f"[CONDITIONAL] ⚠️ Skipped commentary pattern: {text[:80]}")
            return False
    
    # Must have over/under trigger
    has_over_trigger = CONDITIONAL_TRIGGER_PATTERN.search(text) is not None
    has_under_trigger = CONDITIONAL_TRIGGER_UNDER_PATTERN.search(text) is not None
    
    if not (has_over_trigger or has_under_trigger):
        return False
    
    # Validate the matched symbol is not a trade keyword (SL, PT, TP, etc.)
    # These are stop-loss/profit-target prefixes, not ticker symbols
    trade_keywords = {'SL', 'PT', 'TP', 'BE', 'STOP', 'LOSS', 'TRAIL', 'TARG'}
    # Common English words that get falsely matched as tickers in hype messages
    # e.g. "NOTHING BUT BANGERS THIS WEEK\n\nOver 3500% OF GAINS" -> "WEEK over $3500"
    english_stopwords = {
        'WEEK', 'WEEKS', 'DAY', 'DAYS', 'MONTH', 'YEAR', 'TODAY', 'TONITE',
        'GAINS', 'GAIN', 'LOSS', 'LOSSES', 'PROFIT', 'PROFITS', 'WIN', 'WINS',
        'THIS', 'THAT', 'THESE', 'THOSE', 'WITH', 'FROM', 'INTO', 'OVER',
        'UNDER', 'ABOVE', 'BELOW', 'JUST', 'ONLY', 'BUT', 'AND', 'NOT', 'FOR',
        'ALL', 'ANY', 'NEW', 'OLD', 'BIG', 'HUGE', 'TINY', 'NICE',
        'GOOD', 'BAD', 'BEST', 'HIGH', 'LOW', 'UP', 'DOWN', 'IN', 'OUT',
        'HERE', 'THERE', 'NOW', 'SOON', 'NEXT', 'LAST', 'FIRST', 'WAY',
        'WAYS', 'TIME', 'TIMES', 'LOL', 'OMG', 'WOW', 'YES', 'NO',
    }
    trigger_match = CONDITIONAL_TRIGGER_PATTERN.search(text) or CONDITIONAL_TRIGGER_UNDER_PATTERN.search(text)
    if trigger_match:
        matched_symbol = trigger_match.group(1).upper()
        if matched_symbol in trade_keywords:
            return False
        if matched_symbol in english_stopwords:
            print(f"[CONDITIONAL] ⚠️ Skipped hype/stopword as ticker: '{matched_symbol}' in: {text[:80]}")
            return False
        # Reject if the matched price is immediately followed by '%' — that's a
        # percentage in marketing copy ("Over 3500% OF GAINS"), not a price level.
        try:
            price_str = trigger_match.group(2)
            tail_idx = trigger_match.end(2)
            tail = text[tail_idx:tail_idx + 4]
            if re.match(r'\s*%', tail):
                print(f"[CONDITIONAL] ⚠️ Skipped percentage (not price): '{matched_symbol} ... {price_str}%' in: {text[:80]}")
                return False
        except (IndexError, AttributeError):
            pass
    
    # If require_sl_pt is False, allow trigger-only signals (SL/PT can come in follow-up)
    if not require_sl_pt:
        return True
    
    # Check for SL/PT/position size in the same message
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
    try:
        trigger_price = float(trigger_match.group(2))
    except (ValueError, TypeError):
        print(f"[PARSER] ⚠️ Invalid trigger price: '{trigger_match.group(2)}'")
        return None
    
    stop_loss_type = None
    stop_loss_value = None
    stop_loss_fixed = None
    stop_loss_pct = None
    
    try:
        hybrid_sl_match = HYBRID_SL_PATTERN.search(text)
        if hybrid_sl_match:
            fixed = hybrid_sl_match.group('fixed') or hybrid_sl_match.group('fixed_second')
            pct = hybrid_sl_match.group('pct') or hybrid_sl_match.group('pct_first')
            if fixed and pct:
                stop_loss_type = 'hybrid'
                stop_loss_fixed = float(fixed)
                stop_loss_pct = float(pct)
                stop_loss_value = stop_loss_fixed
        
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
    except (ValueError, TypeError) as e:
        print(f"[PARSER] ⚠️ Could not parse stop loss value (typo?): {e} - continuing without SL")
        stop_loss_type = None
        stop_loss_value = None
        stop_loss_fixed = None
        stop_loss_pct = None
    
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
        profit_targets.append((min_price + max_price) / 2)
    
    # If no ranges found, check for percentage-based targets first (e.g., "first target 10% (7.15)")
    if not target_ranges:
        pt_pct_match = CONDITIONAL_PT_PERCENT_PATTERN.search(text)
        if pt_pct_match:
            pt_pct = float(pt_pct_match.group(1))
            explicit_price = pt_pct_match.group(2)
            if explicit_price:
                profit_targets.append(float(explicit_price))
                print(f"[CONDITIONAL]   PT: {pt_pct}% -> explicit ${explicit_price}")
            elif trigger_price:
                calculated_pt = round(trigger_price * (1 + pt_pct / 100), 4)
                profit_targets.append(calculated_pt)
                print(f"[CONDITIONAL]   PT: {pt_pct}% of ${trigger_price} -> ${calculated_pt}")
        else:
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
    Also handles full exits: "out of POLA", "selling XTLB"
    
    Returns dict with:
        - action: 'PARTIAL_EXIT', 'LEAVE_RUNNER', or 'FULL_EXIT'
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
    
    exit_match = PARTIAL_EXIT_PATTERN.search(text)
    if exit_match:
        percent = exit_match.group('percent')
        fraction = exit_match.group('fraction')
        symbol = exit_match.group('symbol')
        pre_symbol = exit_match.group('pre_symbol')
        pre_percent = exit_match.group('pre_percent')
        
        if pre_symbol and pre_percent:
            symbol = pre_symbol
            exit_pct = float(pre_percent)
        elif fraction:
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
    
    # Check for full exit patterns: "out of POLA", "out of SEGG with remaining shares"
    full_exit_match = FULL_EXIT_PATTERN.search(text)
    if full_exit_match:
        symbol = full_exit_match.group('symbol')
        
        result = {
            'format': 'FULL_EXIT',
            'action': 'FULL_EXIT',
            'exit_percent': 100.0,
            'symbol': symbol.upper() if symbol else None,
            '_original_message': text,
        }
        
        print(f"[FULL EXIT] Closing 100% of {symbol.upper() if symbol else 'position'}")
        return result
    
    # Check for direct sell without percentage: "selling XTLB" (implies 100%)
    direct_sell_match = DIRECT_SELL_PATTERN.search(text)
    if direct_sell_match:
        symbol = direct_sell_match.group('symbol')
        
        result = {
            'format': 'FULL_EXIT',
            'action': 'FULL_EXIT',
            'exit_percent': 100.0,
            'symbol': symbol.upper() if symbol else None,
            '_original_message': text,
        }
        
        print(f"[FULL EXIT] Selling 100% of {symbol.upper() if symbol else 'position'}")
        return result
    
    # Check for trimming pattern: "trimming GITS", "trimmed PAVM" (implies 50%)
    trimming_match = TRIMMING_PATTERN.search(text)
    if trimming_match:
        symbol = trimming_match.group('symbol')
        
        result = {
            'format': 'PARTIAL_EXIT',
            'action': 'PARTIAL_EXIT',
            'exit_percent': 50.0,
            'symbol': symbol.upper() if symbol else None,
            '_original_message': text,
        }
        
        print(f"[PARTIAL EXIT] Trimming 50% of {symbol.upper() if symbol else 'position'}")
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


def parse_phoenix_next_target(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse Phoenix "next target" signals like "next target 3.95-4", "target 2.70".
    
    These indicate profit target updates for active positions.
    """
    match = PHOENIX_NEXT_TARGET_PATTERN.search(text)
    if match:
        price1 = float(match.group('price1'))
        price2 = match.group('price2')
        
        if price2:
            # Range target: use midpoint or keep both
            target_min = price1
            target_max = float(price2)
            target_price = (target_min + target_max) / 2
        else:
            target_min = target_max = target_price = price1
        
        result = {
            'format': 'NEXT_TARGET',
            'action': 'UPDATE_TARGET',
            'target_price': target_price,
            'target_min': target_min,
            'target_max': target_max,
            '_original_message': text,
        }
        
        if price2:
            print(f"[PHOENIX] Next target range: ${target_min}-${target_max}")
        else:
            print(f"[PHOENIX] Next target: ${target_price}")
        return result
    
    return None


def parse_phoenix_stop_hit(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse Phoenix "hit SL" / "stopped out" signals.
    
    These indicate the stop loss was triggered.
    """
    match = PHOENIX_STOP_HIT_PATTERN.search(text)
    if match:
        result = {
            'format': 'STOP_HIT',
            'action': 'FULL_EXIT',
            'exit_percent': 100.0,
            'reason': 'stop_loss',
            '_original_message': text,
        }
        
        print(f"[PHOENIX] Stop loss hit - full exit")
        return result
    
    return None


def is_phoenix_exit_signal(text: str) -> bool:
    """Check if text is a Phoenix-style exit signal."""
    return (
        is_partial_exit_signal(text) or
        PHOENIX_NEXT_TARGET_PATTERN.search(text) is not None or
        PHOENIX_STOP_HIT_PATTERN.search(text) is not None
    )


def parse_phoenix_exit_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse Phoenix-style exit signals including:
    - "selling 90% here"
    - "selling 70%"
    - "next target 3.95-4"
    - "hit SL"
    - "leaving 10% here GITS"
    
    Returns parsed exit signal or None.
    """
    # Try partial exit first (selling X%, leaving X%)
    partial = parse_partial_exit_signal(text)
    if partial:
        return partial
    
    # Try next target pattern
    target = parse_phoenix_next_target(text)
    if target:
        return target
    
    # Try stop hit pattern
    stop_hit = parse_phoenix_stop_hit(text)
    if stop_hit:
        return stop_hit
    
    return None
    
    return None


def parse_follow_up_update(text: str, context_symbol: str = None) -> Optional[Dict[str, Any]]:
    """
    Parse follow-up messages for SL/PT updates.
    
    These are messages that update an existing order's SL or PT.
    Examples: "SL now at 14.60", "PT raised to 17.50", "SL 10%", "targets 3.25-3.50"
    
    Args:
        text: Message text
        context_symbol: Symbol from context (previous messages)
        
    Returns:
        Dict with update type and value, or None if not a follow-up update
    """
    updates = {}
    
    # Check for percentage SL FIRST (e.g., "SL 10%", "stop loss 5%")
    sl_pct_match = FOLLOW_UP_SL_PERCENT_PATTERN.search(text)
    if sl_pct_match:
        pct_str = sl_pct_match.group('pct')
        updates['stop_loss_pct_update'] = float(pct_str)
    else:
        # Check for fixed-price SL (e.g., "SL at 2.50")
        sl_match = FOLLOW_UP_SL_PATTERN.search(text)
        if sl_match:
            price_str = sl_match.group('price')
            updates['stop_loss_update'] = float(price_str)
    
    # Check for range PT FIRST (e.g., "targets 3.25-3.50")
    pt_range_match = FOLLOW_UP_PT_RANGE_PATTERN.search(text)
    if pt_range_match:
        price1 = float(pt_range_match.group('price1'))
        price2 = float(pt_range_match.group('price2'))
        updates['profit_targets_update'] = [price1, price2]
    else:
        # Check for single PT (e.g., "PT raised to 3.25")
        pt_match = FOLLOW_UP_PT_PATTERN.search(text)
        if pt_match:
            price_str = pt_match.group('price')
            updates['profit_target_update'] = float(price_str)
    
    if updates:
        embedded_symbol = None
        sym_patterns = [
            re.search(r'(?:targets?|PT|SL|stop\s*loss)\s+(?:for|of|on)\s+\$?([A-Z]{1,5})\b', text, re.IGNORECASE),
            re.search(r'(?:targets?|PT)\s+([A-Z]{1,5})\s+[\d.]', text, re.IGNORECASE),
            re.search(r'(?:SL|stop\s*loss)\s+(?:for|of|on)\s+\$?([A-Z]{1,5})\b', text, re.IGNORECASE),
            re.search(r'(?:second|first|third|next)\s+target\s+([A-Z]{1,5})\s+[\d.]', text, re.IGNORECASE),
        ]
        for m in sym_patterns:
            if m:
                candidate = m.group(1).upper()
                reserved = {'FOR', 'OF', 'ON', 'AT', 'TO', 'NOW', 'HIT', 'MY', 'THE', 'SET', 'HERE', 'MORE', 'WITH'}
                if candidate not in reserved:
                    embedded_symbol = candidate
                    break

        resolved_symbol = embedded_symbol or context_symbol

        result = {
            'format': 'FOLLOW_UP_UPDATE',
            'action': 'UPDATE',
            'symbol': resolved_symbol,
            **updates,
            '_original_message': text,
        }
        
        update_strs = []
        if 'stop_loss_update' in updates:
            update_strs.append(f"SL=${updates['stop_loss_update']}")
        if 'stop_loss_pct_update' in updates:
            update_strs.append(f"SL={updates['stop_loss_pct_update']}%")
        if 'profit_target_update' in updates:
            update_strs.append(f"PT=${updates['profit_target_update']}")
        if 'profit_targets_update' in updates:
            pts = updates['profit_targets_update']
            update_strs.append(f"PT=${pts[0]}-${pts[1]}")
        
        print(f"[FOLLOW-UP] Update detected: {', '.join(update_strs)}"
              f"{' for ' + resolved_symbol if resolved_symbol else ''}")
        return result
    
    return None


def is_partial_exit_signal(text: str) -> bool:
    """
    Check if text is a partial/full exit signal.
    
    IMPORTANT: This should NOT match standard STC signals like "STC 50% AAPL"
    to avoid intercepting normal exit signals. Only match natural language
    partial exit phrases like "selling 50%", "leaving 10%", "out of SYMBOL", etc.
    """
    text_upper = text.upper().strip()
    
    # Exclude standard STC signals - these should go through normal exit flow
    if text_upper.startswith('STC ') or text_upper.startswith('STC@'):
        return False
    
    # Exclude signals that look like option/stock trade formats
    if re.match(r'^(?:BTO|STC|BTC|STO)\s+', text_upper):
        return False
    
    # Check all exit patterns
    return (PARTIAL_EXIT_PATTERN.search(text) is not None or 
            LEAVING_RUNNER_PATTERN.search(text) is not None or
            FULL_EXIT_PATTERN.search(text) is not None or
            DIRECT_SELL_PATTERN.search(text) is not None or
            TRIMMING_PATTERN.search(text) is not None)


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
    
    from src.core.expiry import normalize_expiry_iso

    if not expiry_text:
        return normalize_expiry_iso("daily")

    expiry_text = expiry_text.strip().upper()

    # Direct MM/DD format
    if re.match(r'^\d{1,2}/\d{1,2}$', expiry_text):
        return normalize_expiry_iso(expiry_text)

    # NEXT WEEK - find next Friday
    if 'NEXT' in expiry_text and 'WEEK' in expiry_text:
        today = datetime.now()
        days_until_friday = (4 - today.weekday()) % 7
        if days_until_friday == 0:
            days_until_friday = 7
        next_friday = today + timedelta(days=days_until_friday)
        return next_friday.strftime("%Y-%m-%d")

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
            return normalize_expiry_iso(f"{month}/{day}")

    # JAN 2ND, DEC 15TH, MAR 3RD format (ordinal dates)
    ordinal_match = re.match(r'([A-Z]+)\s*(\d{1,2})(?:ST|ND|RD|TH)?$', expiry_text)
    if ordinal_match:
        month_str, day = ordinal_match.groups()
        month = month_map.get(month_str)
        if month:
            return normalize_expiry_iso(f"{month}/{day}")

    # JAN 2027, MARCH 2026, JAN / 2027 format - use 3rd Friday of month
    month_year_match = re.match(r'([A-Z]+)\s*/?\s*(\d{4})$', expiry_text)
    if month_year_match:
        month_str, year = month_year_match.groups()
        month = month_map.get(month_str)
        if month:
            year_int = int(year)
            first_day = datetime(year_int, month, 1)
            first_friday = first_day + timedelta(days=(4 - first_day.weekday()) % 7)
            third_friday = first_friday + timedelta(weeks=2)
            return third_friday.strftime("%Y-%m-%d")

    # Just month name (JAN, MARCH) - assume current/next occurrence, 3rd Friday
    for month_name, month_num in month_map.items():
        if month_name in expiry_text:
            today = datetime.now()
            year = today.year
            if month_num < today.month:
                year += 1
            first_day = datetime(year, month_num, 1)
            first_friday = first_day + timedelta(days=(4 - first_day.weekday()) % 7)
            third_friday = first_friday + timedelta(weeks=2)
            return third_friday.strftime("%Y-%m-%d")

    return normalize_expiry_iso("daily")


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


def _parse_jake_expiry(expiry_text: str) -> str:
    """Parse Jake's expiry format into YYYY-MM-DD."""
    from src.core.expiry import normalize_expiry_iso

    if not expiry_text:
        return ''

    month_map = {
        'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
        'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12
    }

    match = re.match(r'^(\d{1,2})([A-Z]{3})(\d{2,4})?$', expiry_text.upper())
    if match:
        day, month, year = match.groups()
        month_num = month_map.get(month, 1)
        year_hint = year if year else None
        return normalize_expiry_iso(f"{month_num}/{day}", year_hint=year_hint)

    return normalize_expiry_iso(expiry_text)


def is_jake_signal(text: str) -> bool:
    """Check if text matches Jake signal format."""
    # Skip position update headers (informational, not actionable)
    if JAKE_POSITION_UPDATE_HEADER.search(text):
        return False
    # Entry: **SYMBOL** $STRIKEc|p EXPIRY @lim PRICE
    if JAKE_ENTRY_PATTERN.search(text):
        return True
    # Exit: **SYMBOL** +XX% @limPRICE
    if JAKE_EXIT_PATTERN.search(text):
        return True
    # Extended patterns: +QTY entries, all out, sell orders
    if JAKE_QTY_STOCK_ENTRY.search(text):
        return True
    if JAKE_QTY_OPTION_ENTRY.search(text):
        return True
    if JAKE_ALL_OUT_PATTERN.search(text):
        return True
    if JAKE_PCT_EXIT_EXTENDED.search(text):
        return True
    if JAKE_SELL_ORDER_PATTERN.search(text):
        return True
    return False


def parse_jake_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse Jake's channel format signals into structured dict.
    
    Entry examples:
    - **MSTR** $188c 19DEC2025 @lim3.0
    - **COIN** $330p 27JUN @lim2.07
    - **IWM** $244p 09OCT2025 @ lim0.10-0.20
    - +2 **SNOW** @lim0.11 (stock with qty)
    - +1 **$RGTI** $26c @lim0.80 (option with qty)
    - +2 $**BBAI** $8c 16JAN2026 @lim0.37 (option with qty and expiry)
    
    Exit/Update examples:
    - **IREN** +61% @lim2.29
    - **SNOW** +50% @lim5.2ish
    - All out of **ONON** @lim1.07 for +52%
    - ## $NBIS +100% @lim8.20
    - Sell order already initiated @lim3.20
    
    Returns structured dict with symbol, strike, opt_type, expiry, price, qty, action.
    """
    if not text:
        return None
    
    # Skip position update headers (informational, not actionable)
    if JAKE_POSITION_UPDATE_HEADER.search(text):
        return None
    
    # Clean text - remove @everyone, @here, role mentions
    clean_text = re.sub(r'@everyone|@here|<@&\d+>|<#\d+>', '', text).strip()
    
    # === EXIT PATTERNS (check first) ===
    
    # Try exit pattern: **SYMBOL** +XX% @limPRICE
    match = JAKE_EXIT_PATTERN.search(clean_text)
    if match:
        symbol, pct_gain, price = match.groups()
        return {
            'action': 'STC',
            'symbol': symbol.upper(),
            'price': float(price),
            'pct_gain': float(pct_gain),
            'qty': None,  # Close all
            'is_exit': True,
            '_jake': True,
            '_needs_position_lookup': True,
        }
    
    # Try extended exit pattern: ## $SYMBOL +XX% @limPRICE
    match = JAKE_PCT_EXIT_EXTENDED.search(clean_text)
    if match:
        symbol, pct_gain, price = match.groups()
        return {
            'action': 'STC',
            'symbol': symbol.upper(),
            'price': float(price),
            'pct_gain': float(pct_gain),
            'qty': None,
            'is_exit': True,
            '_jake': True,
            '_needs_position_lookup': True,
        }
    
    # Try all out pattern: All out of **SYMBOL** @limPRICE
    match = JAKE_ALL_OUT_PATTERN.search(clean_text)
    if match:
        symbol, price = match.groups()
        return {
            'action': 'STC',
            'symbol': symbol.upper(),
            'price': float(price),
            'qty': None,  # Close all
            'is_exit': True,
            '_jake': True,
            '_needs_position_lookup': True,
        }
    
    # Try sell order pattern: Sell order @limPRICE
    match = JAKE_SELL_ORDER_PATTERN.search(clean_text)
    if match:
        price = match.group(1)
        return {
            'action': 'STC',
            'symbol': None,  # Needs position lookup
            'price': float(price),
            'qty': None,
            'is_exit': True,
            '_jake': True,
            '_needs_position_lookup': True,
            '_needs_symbol_lookup': True,
        }
    
    # === ENTRY PATTERNS ===
    
    # Try option entry with quantity: +QTY $SYMBOL $STRIKEc/p EXPIRY @limPRICE
    match = JAKE_QTY_OPTION_ENTRY.search(clean_text)
    if match:
        qty, symbol, strike, opt_type, expiry_text, price = match.groups()
        expiry = _parse_jake_expiry(expiry_text) if expiry_text else None
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
            '_jake': True,
        }
    
    # Try stock entry with quantity: +QTY **SYMBOL** @limPRICE
    match = JAKE_QTY_STOCK_ENTRY.search(clean_text)
    if match:
        qty, symbol, price = match.groups()
        return {
            'asset': 'stock',
            'action': 'BTO',
            'symbol': symbol.upper(),
            'price': float(price),
            'qty': int(qty),
            '_qty_from_signal': True,
            '_jake': True,
        }
    
    # Try original entry pattern: **SYMBOL** $STRIKEc|p EXPIRY @lim PRICE
    match = JAKE_ENTRY_PATTERN.search(clean_text)
    if match:
        symbol, strike, opt_type, expiry_text, price = match.groups()
        expiry = _parse_jake_expiry(expiry_text)
        return {
            'asset': 'option',
            'action': 'BTO',
            'symbol': symbol.upper(),
            'strike': float(strike),
            'opt_type': opt_type.upper(),
            'expiry': expiry,
            'price': float(price),
            'qty': None,  # Use channel defaults
            '_qty_from_signal': False,
            '_jake': True,
        }
    
    return None


def is_order_executed_signal(text: str) -> bool:
    """
    Check if text matches the 'Order Executed' broker confirmation format.
    
    Examples:
    - Order Executed\nBought 5 Single SNDK 1/9/2026 360 CALL @4.80 [Buy Open]
    - Order Executed\nSold -1 Single SNDK 1/9/2026 360 CALL @9.40 [Sell Close]
    """
    if not text:
        return False
    
    # Check for signature patterns
    if 'Order Executed' in text or 'order executed' in text.lower():
        if ORDER_EXECUTED_BUY_PATTERN.search(text) or ORDER_EXECUTED_SELL_PATTERN.search(text):
            return True
    
    # Also check for just "Bought/Sold X Single" without header
    if ORDER_EXECUTED_BUY_PATTERN.search(text) or ORDER_EXECUTED_SELL_PATTERN.search(text):
        return True
    
    return False


def parse_order_executed_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse 'Order Executed' broker confirmation signals.
    
    Examples:
    - Order Executed\nBought 5 Single SNDK 1/9/2026 360 CALL @4.80 [Buy Open]
    - Order Executed\nSold -1 Single SNDK 1/9/2026 360 CALL @9.40 [Sell Close]
    
    Returns structured dict with action, qty, symbol, expiry, strike, opt_type, price.
    """
    if not text:
        return None
    
    from src.core.expiry import normalize_expiry_iso

    # Try buy pattern first
    match = ORDER_EXECUTED_BUY_PATTERN.search(text)
    if match:
        qty, symbol, expiry, strike, opt_type, price = match.groups()

        return {
            'asset': 'option',
            'action': 'BTO',
            'symbol': symbol.upper(),
            'strike': float(strike),
            'opt_type': 'C' if opt_type.upper() == 'CALL' else 'P',
            'expiry': normalize_expiry_iso(expiry),
            'price': float(price),
            'qty': int(qty),
            '_qty_from_signal': True,
            '_order_executed': True,
            'is_exit': False,
        }

    # Try sell pattern
    match = ORDER_EXECUTED_SELL_PATTERN.search(text)
    if match:
        qty, symbol, expiry, strike, opt_type, price = match.groups()

        qty_val = abs(int(qty))

        return {
            'asset': 'option',
            'action': 'STC',
            'symbol': symbol.upper(),
            'strike': float(strike),
            'opt_type': 'C' if opt_type.upper() == 'CALL' else 'P',
            'expiry': normalize_expiry_iso(expiry),
            'price': float(price),
            'qty': qty_val,
            '_qty_from_signal': True,
            '_order_executed': True,
            'is_exit': True,
        }
    
    return None


def is_bishop_signal(text: str) -> bool:
    """
    Check if text matches Bishop format signals (usually in embeds).
    
    Examples:
    - **Option:** TSLA 437.50 C 1/9\n**Entry:** 2.48
    - **Option:** HOOD 140 C 2/20\n**Entry:** 3.35-3.36
    - Trimming CAT 640 C 1/16 @$11.25
    """
    if not text:
        return False
    
    if BISHOP_ENTRY_PATTERN.search(text):
        return True
    if BISHOP_TRIMMING_PERCENT_PATTERN.search(text):
        return True
    if BISHOP_TRIMMING_PATTERN.search(text):
        return True
    if BISHOP_EXIT_PATTERN.search(text):
        return True
    return False


def parse_bishop_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse Bishop format signals into structured dict.
    
    Entry format:
    - **Option:** TSLA 437.50 C 1/9\n**Entry:** 2.48
    
    Exit formats:
    - Trimming CAT 640 C 1/16 @$11.25
    - Out of SNOW calls swing for -35%
    
    Returns structured dict with action, symbol, strike, opt_type, expiry, price.
    """
    if not text:
        return None
    
    from src.core.expiry import normalize_expiry_iso

    # Try entry pattern: **Option:** SYMBOL STRIKE C/P EXPIRY ... **Entry:** PRICE or PRICE-PRICE
    match = BISHOP_ENTRY_PATTERN.search(text)
    if match:
        groups = match.groups()
        symbol, strike, opt_type, expiry, price_low = groups[:5]
        price_high = groups[5] if len(groups) > 5 else None

        execution_price = float(price_high) if price_high else float(price_low)

        result = {
            'asset': 'option',
            'action': 'BTO',
            'symbol': symbol.upper(),
            'strike': float(strike),
            'opt_type': opt_type.upper(),
            'expiry': normalize_expiry_iso(expiry),
            'price': execution_price,  # Use higher price for execution
            'price_low': float(price_low),  # Original low price
            'qty': None,
            '_qty_from_signal': False,
            '_bishop': True,
            'is_exit': False,
        }
        
        # If entry has a range (e.g., 3.30-3.40), store both prices
        if price_high:
            result['price_high'] = float(price_high)
            result['entry_high'] = float(price_high)
        
        return result
    
    # Try percent-based trimming pattern FIRST: "Trimming MRK 115 C 2/20 @$190%!!"
    match = BISHOP_TRIMMING_PERCENT_PATTERN.search(text)
    if match:
        symbol, strike, opt_type, expiry, pct_value = match.groups()
        return {
            'asset': 'option',
            'action': 'STC',
            'symbol': symbol.upper(),
            'strike': float(strike),
            'opt_type': opt_type.upper(),
            'expiry': normalize_expiry_iso(expiry),
            'price': 0.0,
            'pct_gain': float(pct_value),
            'trim_percent': float(pct_value),
            'qty': None,
            '_bishop': True,
            '_bishop_trim_percent': True,
            'is_exit': True,
            'is_partial': True,
        }
    
    # Try price-based trimming pattern: "Trimming CAT 640 C 1/16 @$11.25"
    match = BISHOP_TRIMMING_PATTERN.search(text)
    if match:
        symbol, strike, opt_type, expiry, price = match.groups()
        pct_match = re.search(r'([+-]?\d+(?:\.\d+)?)\s*%', text)
        pct = float(pct_match.group(1)) if pct_match else None

        return {
            'asset': 'option',
            'action': 'STC',
            'symbol': symbol.upper(),
            'strike': float(strike),
            'opt_type': opt_type.upper(),
            'expiry': normalize_expiry_iso(expiry),
            'price': float(price),
            'pct_gain': pct,
            'qty': None,
            '_bishop': True,
            'is_exit': True,
            'is_partial': True,
        }
    
    # Try exit pattern: "Out of SNOW calls swing for -35%"
    match = BISHOP_EXIT_PATTERN.search(text)
    if match:
        symbol = match.group(1)
        # Try to extract percentage
        pct_match = re.search(r'([+-]?\d+(?:\.\d+)?)\s*%', text)
        pct = float(pct_match.group(1)) if pct_match else None
        
        return {
            'asset': 'option',
            'action': 'STC',
            'symbol': symbol.upper(),
            'pct_gain': pct,
            'qty': None,
            '_bishop': True,
            'is_exit': True,
            '_needs_position_lookup': True,
        }
    
    return None


def is_evapanda_signal(text: str) -> bool:
    """
    Check if text matches EvaPanda format signals.
    
    Examples:
    - BTO AVGO 01/30/26 400C @ 1.42 (risky swing)
    - STC SPY 01/15/26 700C @ 1.12 (all out on runner)
    """
    if not text:
        return False
    
    return bool(EVAPANDA_PATTERN.search(text))


def parse_evapanda_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse EvaPanda format signals into structured dict.
    
    Format: BTO SYMBOL MM/DD/YY STRIKE+C/P @ PRICE (notes)
    
    Examples:
    - BTO AVGO 01/30/26 400C @ 1.42 (risky swing)
    - STC SPY 01/15/26 700C @ 1.12 (all out on runner)
    - BTO NFLX 08/26/2026 130c @ 1.83 (Long Swing)
    
    Returns structured dict with action, symbol, strike, opt_type, expiry, price.
    """
    if not text:
        return None
    
    match = EVAPANDA_PATTERN.search(text)
    if match:
        from src.core.expiry import normalize_expiry_iso
        action, symbol, expiry_raw, strike, opt_type, price = match.groups()

        is_exit = action.upper() == 'STC'

        return {
            'asset': 'option',
            'action': action.upper(),
            'symbol': symbol.upper(),
            'strike': float(strike),
            'opt_type': opt_type.upper(),
            'expiry': normalize_expiry_iso(expiry_raw),
            'price': float(price),
            'qty': None,
            '_qty_from_signal': False,
            '_evapanda': True,
            'is_exit': is_exit,
        }
    
    return None


def is_toon_signal(text: str) -> bool:
    """
    Check if text matches Toon format signals.
    
    Examples:
    - BTO spy 1/16 692p @ m gonna swing these
    - stc spy 1/16 692p @ m partial
    """
    if not text:
        return False
    
    return bool(TOON_ENTRY_PATTERN.search(text) or TOON_EXIT_PATTERN.search(text))


def parse_toon_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse Toon format signals into structured dict.
    
    Format: BTO/STC SYMBOL MM/DD STRIKE+C/P @ m [partial]
    
    Examples:
    - BTO spy 1/16 692p @ m gonna swing these
    - BTO spy 1/23 692p @ m
    - stc spy 1/16 692p @ m partial (partial exit)
    - stc spy 1/16 692p @ m (full close)
    
    Returns structured dict with action, symbol, strike, opt_type, expiry.
    Price is None since "@ m" means market order.
    """
    if not text:
        return None
    
    from src.core.expiry import normalize_expiry_iso

    # Try entry pattern first
    match = TOON_ENTRY_PATTERN.search(text)
    if match:
        action, symbol, expiry, strike, opt_type = match.groups()

        return {
            'asset': 'option',
            'action': action.upper(),
            'symbol': symbol.upper(),
            'strike': float(strike),
            'opt_type': opt_type.upper(),
            'expiry': normalize_expiry_iso(expiry),
            'price': None,
            'is_market_order': True,
            'qty': None,
            '_qty_from_signal': False,
            '_toon': True,
            'is_exit': False,
        }

    # Try exit pattern
    match = TOON_EXIT_PATTERN.search(text)
    if match:
        action, symbol, expiry, strike, opt_type, partial_flag = match.groups()

        is_partial = partial_flag is not None and partial_flag.lower() == 'partial'

        return {
            'asset': 'option',
            'action': action.upper(),
            'symbol': symbol.upper(),
            'strike': float(strike),
            'opt_type': opt_type.upper(),
            'expiry': normalize_expiry_iso(expiry),
            'price': None,
            'is_market_order': True,
            'qty': None,
            '_qty_from_signal': False,
            '_toon': True,
            'is_exit': True,
            'is_partial': is_partial,
            '_needs_position_lookup': True,
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
        from src.core.expiry import normalize_expiry_iso
        expiry = normalize_expiry_iso("daily")
        
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
        return next_tuesday.strftime("%Y-%m-%d")
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

        return last_tuesday.strftime("%Y-%m-%d") if last_tuesday else now.strftime("%Y-%m-%d")


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
    
    Also supports conditional triggers in multi-line signals:
    Example: "BTO 2 QQQ 608P 1/16 @m\nBELOW QQQ 607"
    
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
    
    result = {
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
    
    # Check for conditional triggers in full text
    # Supports both formats:
    #   "QQQ above 500" (SYMBOL above/below PRICE)
    #   "ABOVE QQQ 500" (ABOVE/BELOW SYMBOL PRICE)
    trigger_match = CONDITIONAL_TRIGGER_PATTERN.search(text)
    trigger_condition = 'above'
    
    if not trigger_match:
        trigger_match = CONDITIONAL_TRIGGER_ABOVE_ALT_PATTERN.search(text)
        trigger_condition = 'above'
    
    if not trigger_match:
        trigger_match = CONDITIONAL_TRIGGER_UNDER_PATTERN.search(text)
        trigger_condition = 'below'
    
    if not trigger_match:
        trigger_match = CONDITIONAL_TRIGGER_UNDER_ALT_PATTERN.search(text)
        trigger_condition = 'below'
    
    if trigger_match:
        trigger_symbol = trigger_match.group(1).upper()
        trigger_price = float(trigger_match.group(2))
        result['trigger_symbol'] = trigger_symbol
        result['trigger_price'] = trigger_price
        result['trigger_condition'] = trigger_condition
        print(f"[SIGNAL] ✓ Conditional trigger detected: {trigger_symbol} {trigger_condition.upper()} ${trigger_price}")
    
    return result


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
