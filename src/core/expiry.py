"""
Centralized expiry normalization — single source of truth for ALL date handling.

Canonical internal format: YYYY-MM-DD (ISO 8601 date string).
Every signal parser, broker API, risk engine path, and sync service
should normalize through this module.

Broker-specific output adapters convert FROM canonical:
  - Schwab/Alpaca: YYYY-MM-DD (native)
  - IBKR: YYYYMMDD
  - Tastytrade: datetime.date object
  - Webull: MM/DD (for display) + option_id (for execution)
  - OCC symbol: YYMMDD
"""

import re
from datetime import date, datetime, timedelta
from typing import Optional

_MONTH_NAMES = {
    'jan': 1, 'january': 1,
    'feb': 2, 'february': 2,
    'mar': 3, 'march': 3,
    'apr': 4, 'april': 4,
    'may': 5,
    'jun': 6, 'june': 6,
    'jul': 7, 'july': 7,
    'aug': 8, 'august': 8,
    'sep': 9, 'sept': 9, 'september': 9,
    'oct': 10, 'october': 10,
    'nov': 11, 'november': 11,
    'dec': 12, 'december': 12,
}

_MONTH_NAME_PATTERN = re.compile(
    r'(?:^|[\s,])(' + '|'.join(_MONTH_NAMES.keys()) + r')[\s,.]+(\d{1,2})(?:[\s,]+(\d{2,4}))?',
    re.IGNORECASE
)

_DD_MM_PATTERN = re.compile(r'^(\d{1,2})\.(\d{2})$')


def _rollover_year(m: int, d: int, base_year: int = 0) -> int:
    if base_year <= 0:
        base_year = date.today().year
    try:
        candidate = date(base_year, m, d)
        if candidate < date.today():
            return base_year + 1
    except ValueError:
        return base_year + 1
    return base_year


def normalize_expiry_iso(raw: str, year_hint: Optional[str] = None) -> str:
    """Convert ANY expiry format to YYYY-MM-DD.

    Supported inputs:
      - YYYY-MM-DD        (passthrough)
      - YYYYMMDD          (compact ISO)
      - MM/DD             (assumes current/next year with rollover)
      - M/D               (single-digit month/day)
      - MM/DD/YY          (2-digit year)
      - MM/DD/YYYY        (4-digit year)
      - "daily" / "weekly" / "0dte"  (today's date)
      - "June 10"         (month name + day)
      - "Jun 18 2026"     (month name + day + year)
      - "17.07"           (DD.MM European — ZZ style)
      - "17.07 exp"       (same with exp suffix)

    Args:
        raw: Raw expiry string from any source.
        year_hint: Optional YYYY string to override year inference.

    Returns:
        Canonical YYYY-MM-DD string.

    Raises:
        ValueError: If the input cannot be parsed into a valid date.
    """
    if not raw or not raw.strip():
        return date.today().strftime('%Y-%m-%d')

    s = raw.strip()

    if s.lower() in ('daily', 'weekly', '0dte', '0 dte'):
        return date.today().strftime('%Y-%m-%d')

    if re.match(r'^\d{4}-\d{2}-\d{2}', s):
        return s[:10]

    if re.match(r'^\d{8}$', s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"

    dd_mm = _DD_MM_PATTERN.match(s.split()[0] if ' ' in s else s)
    if dd_mm:
        day_val, month_val = int(dd_mm.group(1)), int(dd_mm.group(2))
        if 1 <= month_val <= 12 and 1 <= day_val <= 31:
            if year_hint:
                yr = int(year_hint) if len(year_hint) == 4 else int('20' + year_hint)
            else:
                yr = _rollover_year(month_val, day_val)
            return f"{yr:04d}-{month_val:02d}-{day_val:02d}"

    month_match = _MONTH_NAME_PATTERN.search(s)
    if month_match:
        month_name = month_match.group(1).lower()
        day_val = int(month_match.group(2))
        year_str = month_match.group(3)
        m = _MONTH_NAMES[month_name]
        if year_str:
            yr = int(year_str) if len(year_str) == 4 else int('20' + year_str)
        elif year_hint:
            yr = int(year_hint) if len(year_hint) == 4 else int('20' + year_hint)
        else:
            yr = _rollover_year(m, day_val)
        return f"{yr:04d}-{m:02d}-{day_val:02d}"

    if '/' in s:
        clean = re.sub(r'\s*exp\.?\s*$', '', s, flags=re.IGNORECASE).strip()
        parts = clean.split('/')
        if len(parts) == 2:
            m, d = int(parts[0]), int(parts[1])
            if year_hint:
                yr = int(year_hint) if len(year_hint) == 4 else int('20' + year_hint)
            else:
                yr = _rollover_year(m, d)
            return f"{yr:04d}-{m:02d}-{d:02d}"
        elif len(parts) == 3:
            m, d, y = int(parts[0]), int(parts[1]), parts[2]
            yr = int(y) if len(y) == 4 else int('20' + y)
            return f"{yr:04d}-{m:02d}-{d:02d}"

    raise ValueError(f"Cannot parse expiry: '{raw}'")


# ─── Broker-specific output adapters ─────────────────────────────────────────

def expiry_to_yyyymmdd(iso: str) -> str:
    """YYYY-MM-DD → YYYYMMDD (for IBKR contract construction)."""
    clean = normalize_expiry_iso(iso)
    return clean.replace('-', '')


def expiry_to_date(iso: str) -> date:
    """YYYY-MM-DD → datetime.date (for Tastytrade SDK)."""
    clean = normalize_expiry_iso(iso)
    return date.fromisoformat(clean)


def expiry_to_mmdd(iso: str) -> str:
    """YYYY-MM-DD → MM/DD (for display, cache keys, Webull)."""
    clean = normalize_expiry_iso(iso)
    parts = clean.split('-')
    return f"{parts[1]}/{parts[2]}"


def expiry_to_occ(iso: str) -> str:
    """YYYY-MM-DD → YYMMDD (for OCC option symbol construction)."""
    clean = normalize_expiry_iso(iso)
    parts = clean.split('-')
    return f"{parts[0][2:]}{parts[1]}{parts[2]}"


def expiry_year(iso: str) -> str:
    """YYYY-MM-DD → YYYY (extract year for legacy code paths)."""
    clean = normalize_expiry_iso(iso)
    return clean[:4]


def is_expired(iso: str) -> bool:
    """Check if an expiry date is in the past."""
    try:
        d = expiry_to_date(iso)
        return d < date.today()
    except (ValueError, TypeError):
        return False


def is_same_day(iso: str) -> bool:
    """Check if expiry is today (0DTE)."""
    try:
        d = expiry_to_date(iso)
        return d == date.today()
    except (ValueError, TypeError):
        return False
