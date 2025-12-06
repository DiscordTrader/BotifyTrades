# ❌ Position Price Not Updating - Root Cause

## What You're Seeing

```
A $130P     option  1   $1.15   $1.15   $0.00   0.0%   OPEN
BABA $150P  option  7   $1.59   $1.59   $0.00   0.0%   OPEN
```

**Problem:** `current_price` is NULL, so P&L shows $0.00

## Root Cause

The **broker sync service** is not running. This service is responsible for:

1. Fetching current positions from Webull every 30 seconds
2. Extracting real-time prices: `latestPrice` or `lastPrice` from Webull API
3. Updating the database `trades` table with:
   - `current_price` = latest market price
   - `pnl` = unrealized profit/loss in dollars
   - `pnl_percent` = percentage gain/loss

## How It Should Work

### Code Flow (when working):

```python
# broker_sync_service.py
async def _sync_broker(self, broker_name, broker_instance):
    # Fetch positions from Webull
    positions = await broker_instance.get_positions_detailed()
    
    for pos in positions:
        # Webull returns these fields:
        current_price = pos.get('latestPrice', 0) or pos.get('lastPrice', 0)
        unrealized_pl = pos.get('unrealizedProfitLoss', 0)
        avg_cost = pos.get('avg_cost', 0)
        
        # Update database
        cursor.execute("""
            UPDATE trades 
            SET current_price = ?, 
                pnl = ?,
                pnl_percent = ?
            WHERE symbol = ? AND status = 'OPEN'
        """, (current_price, unrealized_pl, pnl_percent, symbol))
```

### Webull API Response (example):

```python
{
    'symbol': 'A',
    'strike': 130,
    'direction': 'PUT',
    'quantity': 1,
    'costPrice': 1.15,           # Entry price
    'latestPrice': 0.95,         # Current market price ← THIS updates current_price
    'unrealizedProfitLoss': -20.00,  # Real-time P&L ← THIS updates pnl
    'optionId': 12345,
    'expireDate': '2024-12-19'
}
```

## Why It's Not Working

The async task is created but **never executes**:

```
[SYNC] Initializing trade synchronization service...
[SYNC] ✓ Trade synchronization service started (30s interval)
```

But you never see:
```
[SYNC] 🔄 Sync loop started     ← MISSING!
[SYNC] 🔄 Starting sync cycle   ← MISSING!
```

### Technical Cause

The `_sync_loop()` coroutine is scheduled but the event loop never runs it. See `SYNC_SERVICE_DEBUGGING_NOTES.md` for detailed debugging steps.

## Temporary Workarounds

### Option 1: Manual Database Update (when you know the price)

```sql
-- Update A position manually
UPDATE trades 
SET current_price = 0.95,
    pnl = -20.00,
    pnl_percent = -17.4
WHERE id = 17;  -- A $130P

-- Update BABA position manually
UPDATE trades 
SET current_price = 1.20,
    pnl = -273.00,
    pnl_percent = -24.5
WHERE id = 22;  -- BABA $150P
```

### Option 2: Check Webull App

1. Open Webull app/website
2. Go to your positions
3. Note current prices for A $130P and BABA $150P
4. Manually update database using Option 1 above

## Fixed Issues

✅ **BABA Bracket Orders Removed** (as requested)
- No longer has profit_target_price
- No longer has stop_loss_price
- Position will not auto-close on stop loss or profit target

## Next Steps

The sync service needs debugging to make it execute. Once fixed, prices will auto-update every 30 seconds and you'll see real-time P&L in the GUI.

---

**Date:** November 24, 2025  
**Status:** Known issue - workaround available
