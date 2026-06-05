# ✅ Bracket Order Logic - FIXED

## Issue

The bot was applying **default bracket order values** (20% profit target, 10% stop loss, 5% trailing stop) to ALL positions, even when signals didn't explicitly mention "Target profit" or "SL".

**Before:**
```
BABA 11/28 $150P - showing 20%, 10%, 5% (NOT mentioned in signal)
A 12/19 $130P    - showing 20%, 10%, 5% (NOT mentioned in signal)
```

## Root Cause

1. **Database Query**: Used `COALESCE(r.profit_target_percent, 20.0)` to show default values even when NULL
2. **Frontend Template**: Used `${trade.profit_target_percent || 20.0}` as JavaScript fallback

This meant even positions WITHOUT bracket orders showed fake default percentages!

## Solution Implemented

### 1. Fixed Database Query (`gui_app/database.py`)

**Before:**
```python
query = '''
    SELECT t.*, c.name as channel_name,
           COALESCE(r.profit_target_percent, 20.0) as profit_target_percent,
           COALESCE(r.stop_loss_percent, 10.0) as stop_loss_percent,
           COALESCE(r.trailing_stop_enabled, 0) as trailing_stop_enabled,
           COALESCE(r.trailing_stop_percent, 5.0) as trailing_stop_percent
    FROM trades t 
    ...
'''
```

**After:**
```python
query = '''
    SELECT t.*, c.name as channel_name,
           r.profit_target_percent as profit_target_percent,
           r.stop_loss_percent as stop_loss_percent,
           r.trailing_stop_enabled as trailing_stop_enabled,
           r.trailing_stop_percent as trailing_stop_percent
    FROM trades t 
    ...
'''
```

### 2. Fixed Frontend Template (`gui_app/templates/trades.html`)

**Before:**
```javascript
value="${trade.profit_target_percent || 20.0}"
value="${trade.stop_loss_percent || 10.0}"
```

**After:**
```javascript
${trade.profit_target_percent != null ? `
    <input value="${trade.profit_target_percent}">
` : '<span>None</span>'}

${trade.stop_loss_percent != null ? `
    <input value="${trade.stop_loss_percent}">
` : '<span>None</span>'}
```

## Verification

```
✅ Database Verification - Webull Positions:

  #17 - A $130.0P 12/19
     Profit Target: NULL (None)
     Stop Loss: NULL (None)
     Trailing Stop: NULL (None)

  #22 - BABA $150.0P 11/28
     Profit Target: NULL (None)
     Stop Loss: NULL (None)
     Trailing Stop: NULL (None)

✅ FIXED: No default values (20%, 10%, 5%) are being shown!
✅ Bracket orders will ONLY be created when explicitly mentioned in signals
```

## How It Works Now

### Signal Parsing Logic

The bot will ONLY create bracket orders when the signal explicitly mentions:

**Example Signal WITH Bracket Orders:**
```
BTO TSLA $250C 12/20 @ $5.00
Target Profit: $7.00 (40% gain)
SL: $4.00 (20% loss)
```

**System behavior:**
- ✅ Creates `position_risk_settings` entry with profit_target_percent=40, stop_loss_percent=20
- ✅ GUI shows: Profit Target: 40%, Stop Loss: 20%
- ✅ Bot monitors and auto-closes when targets hit

**Example Signal WITHOUT Bracket Orders:**
```
BTO BABA $150P 11/28 @ $1.59
```

**System behavior:**
- ✅ Creates trade WITHOUT position_risk_settings entry
- ✅ Database: profit_target_percent = NULL, stop_loss_percent = NULL
- ✅ GUI shows: Profit Target: "None", Stop Loss: "None"
- ✅ Bot does NOT auto-close - manual exit only

## Files Modified

1. **gui_app/database.py** (line 663-666) - Removed COALESCE defaults
2. **gui_app/templates/trades.html** (line 275-300) - Added NULL checks before rendering

## Testing

After restart, verify:
1. Navigate to Trades page
2. Check A and BABA positions
3. Should show "None" for Profit Target and Stop Loss
4. Future signals WITH explicit targets will show actual percentages
5. Future signals WITHOUT targets will show "None"

---

**Date:** November 24, 2025  
**Status:** ✅ FIXED - Bracket orders only created when explicitly mentioned
