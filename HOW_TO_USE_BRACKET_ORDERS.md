# 📋 How to Use Bracket Orders - User Guide

## What Are Bracket Orders?

Bracket orders automatically close your positions when they hit:
- **Profit Target** - Sell when you've made X% profit
- **Stop Loss** - Sell when you've lost X% to limit losses  
- **Trailing Stop** - Lock in profits by selling when price drops X% from peak

## ✅ When Bracket Orders Are Created

Bracket orders are **ONLY** created when the signal **explicitly mentions** profit targets or stop losses.

### Example Signal WITH Bracket Orders:

```
BTO TSLA $250C 12/20 @ $5.00
Target Profit: $7.00
SL: $4.00
```

**Result:**
- ✅ Creates position with 40% profit target ($7.00 is 40% above $5.00 entry)
- ✅ Creates position with 20% stop loss ($4.00 is 20% below $5.00 entry)
- ✅ Bot auto-monitors and closes when either target hits

### Example Signal WITHOUT Bracket Orders:

```
BTO BABA $150P 11/28 @ $1.59
```

**Result:**
- ✅ Creates position WITHOUT bracket orders
- ✅ NO auto-close
- ✅ You control exit manually

## Signal Format Keywords

The bot recognizes these keywords for bracket orders:

### Profit Target Keywords:
- `Target Profit`
- `Target`
- `TP`
- `Take Profit`
- `Profit Target`

### Stop Loss Keywords:
- `SL`
- `Stop Loss`
- `Stop`

### Example Signals:

```
BTO AAPL $180C 12/15 @ $3.50
Target: $5.00
SL: $2.50
```

```
BTO SPY $450P 12/01 @ $2.00
Take Profit: $3.00 (50% gain)
Stop Loss: $1.50 (25% loss)
```

```
BTO NVDA $500C 01/17 @ $10.00
TP: $15.00
SL: $8.00
Trailing: 5%
```

## GUI Display

### With Bracket Orders:
```
Symbol: TSLA $250C 12/20
Profit Target: [40%]  ← Shows actual percentage
Stop Loss: [20%]      ← Shows actual percentage
Trailing: [ ] 5%      ← Can enable manually
```

### Without Bracket Orders:
```
Symbol: BABA $150P 11/28
Profit Target: None   ← No auto-close on profit
Stop Loss: None       ← No auto-close on loss
Trailing: None        ← No trailing stop
```

## Manual Configuration

You can manually add/edit bracket orders through the web GUI:

1. Go to **Trades** page
2. Find your position
3. Enter percentages in the input fields
4. Click **💾 Save** button
5. Bot will start monitoring that position

## Important Notes

⚠️ **Default Values Removed**: The bot NO LONGER applies default bracket orders (20%, 10%, 5%) to all positions

✅ **Explicit Only**: Bracket orders are ONLY created when:
1. Signal mentions keywords like "Target Profit", "SL", etc.
2. You manually configure them in the GUI

🎯 **Recommended Use**:
- Use bracket orders for high-risk swing trades
- Skip bracket orders for positions you want to manage manually
- Configure trailing stops after entry to lock in profits

---

**Date:** November 24, 2025  
**Status:** Updated - Bracket orders only when explicitly requested
