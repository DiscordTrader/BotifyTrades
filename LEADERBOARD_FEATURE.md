# 🏆 Channel Performance Leaderboard Feature

## What's New?

I've added a **Channel Performance Leaderboard** to your web GUI that ranks all Discord channels by their trading performance!

---

## ✅ Features Implemented

### **1. Leaderboard Page**
- **URL**: http://127.0.0.1:5000/leaderboard
- **Displays**: All tracked channels sorted by win rate (highest to lowest)
- **Auto-Refresh**: Updates every 30 seconds

### **2. Performance Metrics Shown**

For each channel, the leaderboard displays:

| Metric | Description |
|--------|-------------|
| **Rank** | Position (🥇🥈🥉 medals for top 3) |
| **Channel Name** | Discord channel name + total signals |
| **Trades** | Total number of closed positions |
| **Wins** | Number of profitable trades (green) |
| **Losses** | Number of losing trades (red) |
| **Win Rate** | Percentage of winning trades (color-coded) |
| **Total P&L** | Cumulative profit/loss (green/red) |
| **Avg P&L** | Average profit/loss per trade |
| **Best Trade** | Largest winning trade |
| **Worst Trade** | Largest losing trade |

### **3. Summary Statistics**

At the top of the page:
- **Total Channels**: Number of channels with closed trades
- **Best Win Rate**: Highest win rate among all channels
- **Total Closed Trades**: Sum of all closed positions
- **Overall Win Rate**: Win rate across all channels combined

---

## 🎨 UI Design

The leaderboard follows the **Webull dark theme** aesthetic:

- **🥇 Gold, 🥈 Silver, 🥉 Bronze** medals for top 3 channels
- **Color-coded win rates**:
  - Green ≥ 60% (excellent)
  - Yellow ≥ 50% (good)
  - Red < 50% (needs improvement)
- **Green/Red P&L** values for instant recognition
- **Compact, data-dense table** for maximum information
- **Sticky header** stays visible while scrolling

---

## 📊 How It Works

### **Data Source:**
The leaderboard pulls data from your SQLite database:
- Aggregates closed positions from `lot_closures` table
- Joins with `channels`, `signals`, and `signal_lots`
- Calculates win/loss counts and P&L metrics
- Sorts by win rate (descending), then total P&L

### **Calculation Logic:**
```sql
Win Rate = (Wins / Total Closed Trades) × 100%
Avg P&L = Total P&L / Total Closed Trades
```

Only channels with **at least 1 closed trade** appear on the leaderboard.

---

## 🚀 How to Use

### **Access the Leaderboard:**

1. **Start your bot** (if not already running):
   ```cmd
   python src/selfbot_webull.py
   ```

2. **Open browser** to:
   ```
   http://127.0.0.1:5000/leaderboard
   ```

3. **Navigate** using the top menu bar:
   - Dashboard → Channels → Trades → Signals → **Leaderboard** → Settings

### **What You'll See:**

**Example Leaderboard:**
```
Rank  Channel              Trades  Wins  Losses  Win Rate  Total P&L   Avg P&L
🥇    #premium-signals     45      32    13      71.1%     +$2,345.67  +$52.13
🥈    #swing-trades        38      24    14      63.2%     +$1,567.89  +$41.26
🥉    #day-trades          52      28    24      53.8%     +$892.45    +$17.16
4     #options-alerts      29      14    15      48.3%     -$234.56    -$8.09
5     #crypto-signals      18      7     11      38.9%     -$456.78    -$25.38
```

**Interpretation:**
- **#premium-signals** has the best performance (71.1% win rate)
- **#swing-trades** has good consistency (63.2% win rate)
- **#day-trades** is profitable but needs improvement (53.8%)
- **#options-alerts** and **#crypto-signals** need strategy review

---

## 🔧 Technical Details

### **Files Added/Modified:**

| File | What Changed |
|------|-------------|
| `gui_app/database.py` | Added `get_channel_leaderboard()` function (lines 605-689) |
| `gui_app/routes.py` | Added `/leaderboard` page route & `/api/leaderboard` API endpoint |
| `gui_app/templates/leaderboard.html` | New leaderboard page template |
| `gui_app/static/css/style.css` | Added leaderboard-specific CSS styles |

### **Database Function:**
```python
def get_channel_leaderboard():
    """
    Returns list of channels sorted by win rate with:
    - total_signals, total_closed, win_count, loss_count
    - win_rate, total_pnl, avg_pnl
    - best_trade, worst_trade, avg_holding_days
    """
```

### **API Endpoint:**
```
GET /api/leaderboard
Returns: JSON array of channel stats sorted by win_rate DESC
```

---

## 📋 Use Cases

### **1. Channel Comparison**
- Quickly identify which Discord channels provide the best signals
- Compare win rates across multiple signal providers
- Find the most profitable channels

### **2. Performance Tracking**
- Monitor channel performance over time
- Identify improving or declining channels
- Make data-driven decisions about which channels to follow

### **3. Risk Management**
- Spot channels with high loss rates
- Avoid channels with consistent losses
- Focus capital on high-performing channels

### **4. Strategy Optimization**
- See which signal types (day trading vs swing trading) work best
- Compare different trading styles across channels
- Identify your edge

---

## 🎯 Next Steps (Optional Enhancements)

Want to make the leaderboard even better? Consider:

1. **Time Filters**: Add "Last 7 Days", "Last 30 Days", "All Time" filters
2. **Sharpe Ratio**: Calculate risk-adjusted returns
3. **Export**: Download leaderboard as CSV/Excel
4. **Channel Details**: Click a channel to see detailed trade history
5. **Charts**: Add performance charts for each channel

---

## ✅ Summary

**What You Got:**
- ✅ Full-featured channel performance leaderboard
- ✅ Win rate calculations with color-coding
- ✅ P&L tracking per channel
- ✅ Top 3 medals (🥇🥈🥉)
- ✅ Auto-refresh every 30 seconds
- ✅ Dark theme matching Webull design
- ✅ Responsive, data-dense layout

**How to Access:**
```
http://127.0.0.1:5000/leaderboard
```

**Status**: ✅ **LIVE AND WORKING!**

---

## 🐛 Troubleshooting

### **No Channels Showing?**
- **Cause**: No closed trades in database yet
- **Solution**: Execute some BTO signals, then close them with STC signals

### **Leaderboard Shows 0%?**
- **Cause**: Only open positions, no closed trades
- **Solution**: Close some positions to see win/loss statistics

### **Can't Access Page?**
- **Cause**: Bot not running or GUI not started
- **Solution**: Run `python src/selfbot_webull.py` and check logs for:
  ```
  [GUI] ✓ Web control panel started on port 5000
  ```

---

**Your Channel Performance Leaderboard is ready to use!** 🎉

Open http://127.0.0.1:5000/leaderboard and see which channels are performing best! 🏆
