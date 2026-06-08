"""
Analyze guru-futures channel signals.
Entry format: embed fields with Ticker (MNQ/MGC/BTC + LONG/SHORT), Entry price, Stoploss
Exit format: embed description with "N points/ticks trim/exit" or "stoploss"
"""
import json, sys, os, re, glob
from datetime import datetime
from collections import defaultdict

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

files = glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               'extracted_*guru-futures*'))
if not files:
    print("No guru-futures extracted file found")
    sys.exit(1)

with open(files[0], 'r', encoding='utf-8') as f:
    data = json.load(f)

msgs = data['messages']
msgs.reverse()  # oldest first

TICKER_MAP = {
    'MNQ': {'name': 'Micro E-mini Nasdaq', 'tick_value': 0.50, 'unit': 'points'},
    'NQ': {'name': 'E-mini Nasdaq', 'tick_value': 5.00, 'unit': 'points'},
    'MGC': {'name': 'Micro Gold', 'tick_value': 1.00, 'unit': 'ticks'},
    'GC': {'name': 'Gold Futures', 'tick_value': 10.00, 'unit': 'ticks'},
    'BTC': {'name': 'Bitcoin Futures', 'tick_value': 1.00, 'unit': 'dollars'},
    'BTCUSDT': {'name': 'BTC/USDT', 'tick_value': 1.00, 'unit': 'dollars'},
    'ES': {'name': 'E-mini S&P', 'tick_value': 12.50, 'unit': 'points'},
    'MES': {'name': 'Micro E-mini S&P', 'tick_value': 1.25, 'unit': 'points'},
}

def parse_ticker(ticker_text):
    t = ticker_text.replace('`', '').strip().upper()
    if t in ('TEST', 'TEST ULTRA FAST BOT', 'WATCHING MGC AND MNQ', 'WATCHING MGC'):
        return None, None, True
    direction = None
    if 'LONG' in t:
        direction = 'LONG'
    elif 'SHORT' in t:
        direction = 'SHORT'
    symbol = None
    for sym in sorted(TICKER_MAP.keys(), key=len, reverse=True):
        if sym in t:
            symbol = sym
            break
    if not symbol:
        for word in t.split():
            clean = re.sub(r'[^A-Z]', '', word)
            if clean and clean in TICKER_MAP:
                symbol = clean
                break
    if not symbol:
        for word in t.split():
            clean = re.sub(r'[^A-Z]', '', word)
            if clean and len(clean) >= 2:
                symbol = clean
                break
    return symbol, direction, False

def parse_exit_msg(desc):
    desc_clean = re.sub(r'<[^>]+>', '', desc).strip()
    d = desc_clean.lower()

    is_sl = 'stoploss' in d or 'stop loss' in d or d.strip().startswith('sl ')
    is_be = 'breakeven' in d or d.strip() == 'at entry' or 'be ' in d
    is_exit = any(kw in d for kw in ['exit', 'close', 'out '])
    is_trim = 'trim' in d

    pts_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:points?|pts?|ticks?)', d)
    dollar_match = re.search(r'\$\s*(\d+(?:,?\d+)?(?:\.\d+)?)\s*(?:drop|profit|gain|trim)?', d)

    points = None
    dollars = None
    if pts_match:
        points = float(pts_match.group(1))
    if dollar_match:
        dollars = float(dollar_match.group(1).replace(',', ''))

    # Also match bare "N points" at start
    bare_pts = re.match(r'^(\d+(?:\.\d+)?)\s*(?:points?|pts?|ticks?)?(?:\s|$)', d)
    if bare_pts and not points:
        points = float(bare_pts.group(1))

    trim_num = None
    trim_match = re.search(r'trim\s*(\d+)?', d)
    if trim_match:
        trim_num = int(trim_match.group(1)) if trim_match.group(1) else 1

    if is_sl or is_be or is_exit or is_trim or points or dollars:
        return {
            'is_sl': is_sl,
            'is_be': is_be,
            'is_exit': is_exit,
            'is_trim': is_trim,
            'points': points,
            'dollars': dollars,
            'trim_num': trim_num,
            'raw': desc_clean,
        }
    return None


# Parse all messages
entries = []
exit_msgs = []
skipped = 0

for m in msgs:
    ts = m.get('timestamp', '')
    embeds = m.get('embeds', [])
    for e in embeds:
        if e.get('fields'):
            fields = {f['name']: f['value'] for f in e['fields']}
            ticker_raw = fields.get('\U0001f4c8 Ticker:', '')
            entry_raw = fields.get('\U0001f4b5 Entry:', '0')
            sl_raw = fields.get('\U0001f6a8 Stoploss:', '0')
            symbol, direction, is_test = parse_ticker(ticker_raw)
            if is_test:
                skipped += 1
                continue
            try:
                entry_price = float(entry_raw.replace(',', ''))
            except (ValueError, TypeError):
                entry_price = 0
            try:
                sl_price = float(sl_raw.replace(',', ''))
            except (ValueError, TypeError):
                sl_price = 0
            if entry_price <= 0:
                skipped += 1
                continue
            entries.append({
                'symbol': symbol or 'UNKNOWN',
                'direction': direction or 'UNKNOWN',
                'entry': entry_price,
                'stoploss': sl_price,
                'sl_distance': abs(entry_price - sl_price) if sl_price > 0 else 0,
                'time': ts,
                'raw_ticker': ticker_raw,
            })
        elif e.get('description'):
            desc = e['description']
            ex = parse_exit_msg(desc)
            if ex:
                ex['time'] = ts
                exit_msgs.append(ex)

print(f"Parsed {len(entries)} entries, {len(exit_msgs)} exit messages, {skipped} skipped (test/invalid)")

# Match entries with exits chronologically
trades = []
open_positions = []

for entry in entries:
    entry_dt = datetime.fromisoformat(entry['time'].replace('Z', '+00:00'))
    # Find exit messages AFTER this entry, BEFORE next entry of same symbol
    next_entry_time = None
    for e2 in entries:
        e2_dt = datetime.fromisoformat(e2['time'].replace('Z', '+00:00'))
        if e2_dt > entry_dt and (e2['symbol'] == entry['symbol'] or e2['symbol'] == 'UNKNOWN'):
            next_entry_time = e2_dt
            break

    related_exits = []
    for ex in exit_msgs:
        ex_dt = datetime.fromisoformat(ex['time'].replace('Z', '+00:00'))
        if ex_dt <= entry_dt:
            continue
        if next_entry_time and ex_dt >= next_entry_time:
            break
        related_exits.append(ex)

    if related_exits:
        total_points = 0
        total_dollars = 0
        exit_type = 'MANUAL'
        final_exit = related_exits[-1]
        trims = 0

        for ex in related_exits:
            if ex['is_sl']:
                exit_type = 'SL'
                if ex['points']:
                    total_points = -abs(ex['points'])
                elif entry['sl_distance'] > 0:
                    total_points = -entry['sl_distance']
                break
            elif ex['is_be']:
                exit_type = 'BE'
                total_points = 0
                break
            else:
                if ex['points']:
                    total_points = max(total_points, ex['points'])
                if ex['dollars']:
                    total_dollars = max(total_dollars, ex['dollars'])
                if ex['is_trim']:
                    trims += 1

        if exit_type != 'SL' and total_points > 0:
            exit_type = 'WIN'

        ticker_info = TICKER_MAP.get(entry['symbol'], {'tick_value': 1.0, 'unit': 'points'})

        if entry['symbol'] in ('MGC', 'GC'):
            dollar_pnl = total_points * 10 if entry['symbol'] == 'GC' else total_points * 1.0
        elif entry['symbol'] in ('MNQ', 'NQ'):
            dollar_pnl = total_points * 2.0 if entry['symbol'] == 'MNQ' else total_points * 20.0
        elif entry['symbol'] in ('MES', 'ES'):
            dollar_pnl = total_points * 5.0 if entry['symbol'] == 'ES' else total_points * 1.25
        else:
            dollar_pnl = total_dollars if total_dollars else total_points

        if exit_type == 'SL':
            if entry['symbol'] in ('MGC', 'GC'):
                dollar_pnl = total_points * (10 if entry['symbol'] == 'GC' else 1.0)
            elif entry['symbol'] in ('MNQ', 'NQ'):
                dollar_pnl = total_points * (20.0 if entry['symbol'] == 'NQ' else 2.0)
            else:
                dollar_pnl = total_points if total_points else -entry['sl_distance']

        trades.append({
            'symbol': entry['symbol'],
            'direction': entry['direction'],
            'entry': entry['entry'],
            'stoploss': entry['stoploss'],
            'sl_distance': entry['sl_distance'],
            'points': total_points,
            'dollar_pnl': dollar_pnl,
            'exit_type': exit_type,
            'trims': trims,
            'time': entry['time'],
            'raw_ticker': entry['raw_ticker'],
        })
    else:
        open_positions.append(entry)

# Analysis
print("\n" + "="*75)
print(f"   GURU FUTURES CHANNEL ANALYSIS")
print(f"   Channel: {data['channel_name']} ({data['channel_id']})")
print(f"   Messages: {data['message_count']}")
print("="*75)

total = len(trades)
wins = [t for t in trades if t['exit_type'] == 'WIN']
losses = [t for t in trades if t['exit_type'] == 'SL']
breakevens = [t for t in trades if t['exit_type'] == 'BE']
manual = [t for t in trades if t['exit_type'] == 'MANUAL']

win_count = len(wins)
loss_count = len(losses)
be_count = len(breakevens)
win_rate = (win_count / total * 100) if total > 0 else 0
win_rate_excl_be = (win_count / (win_count + loss_count) * 100) if (win_count + loss_count) > 0 else 0

total_points_won = sum(t['points'] for t in wins)
total_points_lost = sum(t['points'] for t in losses)
total_dollar_won = sum(t['dollar_pnl'] for t in wins)
total_dollar_lost = sum(t['dollar_pnl'] for t in losses)
net_points = sum(t['points'] for t in trades)
net_dollars = sum(t['dollar_pnl'] for t in trades)

avg_win_pts = (total_points_won / win_count) if win_count > 0 else 0
avg_loss_pts = (total_points_lost / loss_count) if loss_count > 0 else 0
risk_reward = abs(avg_win_pts / avg_loss_pts) if avg_loss_pts != 0 else float('inf')
profit_factor = abs(total_dollar_won / total_dollar_lost) if total_dollar_lost != 0 else float('inf')

# Streaks
max_win_streak = cur_streak = 0
for t in trades:
    if t['exit_type'] == 'WIN':
        cur_streak += 1
        max_win_streak = max(max_win_streak, cur_streak)
    else:
        cur_streak = 0

max_loss_streak = cur_streak = 0
for t in trades:
    if t['exit_type'] == 'SL':
        cur_streak += 1
        max_loss_streak = max(max_loss_streak, cur_streak)
    else:
        cur_streak = 0

# Per-symbol stats
sym_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'be': 0, 'total': 0,
                                   'pts_won': 0, 'pts_lost': 0, 'dollar_pnl': 0})
for t in trades:
    s = sym_stats[t['symbol']]
    s['total'] += 1
    s['dollar_pnl'] += t['dollar_pnl']
    if t['exit_type'] == 'WIN':
        s['wins'] += 1
        s['pts_won'] += t['points']
    elif t['exit_type'] == 'SL':
        s['losses'] += 1
        s['pts_lost'] += t['points']
    elif t['exit_type'] == 'BE':
        s['be'] += 1

# Per-direction stats
long_trades = [t for t in trades if t['direction'] == 'LONG']
short_trades = [t for t in trades if t['direction'] == 'SHORT']
long_wins = [t for t in long_trades if t['exit_type'] == 'WIN']
short_wins = [t for t in short_trades if t['exit_type'] == 'WIN']
long_wr = (len(long_wins) / len(long_trades) * 100) if long_trades else 0
short_wr = (len(short_wins) / len(short_trades) * 100) if short_trades else 0

# SL analysis
avg_sl_dist = (sum(t['sl_distance'] for t in trades if t['sl_distance'] > 0) /
               sum(1 for t in trades if t['sl_distance'] > 0)) if any(t['sl_distance'] > 0 for t in trades) else 0

print(f"\n{'='*40}")
print(f"  OVERVIEW")
print(f"{'='*40}")
print(f"  Total Trades:          {total}")
print(f"  Wins:                  {win_count}")
print(f"  Losses (SL):           {loss_count}")
print(f"  Breakeven:             {be_count}")
print(f"  Manual Exit:           {len(manual)}")
print(f"  Still Open:            {len(open_positions)}")

print(f"\n{'='*40}")
print(f"  WIN RATE")
print(f"{'='*40}")
print(f"  Win Rate (all):        {win_rate:.1f}%")
print(f"  Win Rate (W vs L):     {win_rate_excl_be:.1f}%")
print(f"  Max Win Streak:        {max_win_streak}")
print(f"  Max Loss Streak:       {max_loss_streak}")

print(f"\n{'='*40}")
print(f"  P&L SUMMARY (per 1 contract)")
print(f"{'='*40}")
print(f"  Net Points:            {net_points:+.1f}")
print(f"  Net P&L (est):         ${net_dollars:+,.2f}")
print(f"  Total Won:             {total_points_won:+.1f} pts (${total_dollar_won:+,.2f})")
print(f"  Total Lost:            {total_points_lost:+.1f} pts (${total_dollar_lost:+,.2f})")
print(f"  Avg Win:               {avg_win_pts:+.1f} pts")
print(f"  Avg Loss:              {avg_loss_pts:+.1f} pts")
print(f"  Risk:Reward:           1:{risk_reward:.2f}")
print(f"  Profit Factor:         {profit_factor:.2f}")

print(f"\n{'='*40}")
print(f"  DIRECTION ANALYSIS")
print(f"{'='*40}")
print(f"  Longs:                 {len(long_trades)} trades, {len(long_wins)} wins ({long_wr:.1f}%)")
print(f"  Shorts:                {len(short_trades)} trades, {len(short_wins)} wins ({short_wr:.1f}%)")
long_pnl = sum(t['dollar_pnl'] for t in long_trades)
short_pnl = sum(t['dollar_pnl'] for t in short_trades)
print(f"  Long P&L:              ${long_pnl:+,.2f}")
print(f"  Short P&L:             ${short_pnl:+,.2f}")

print(f"\n{'='*40}")
print(f"  STOP LOSS ANALYSIS")
print(f"{'='*40}")
print(f"  Avg SL Distance:       {avg_sl_dist:.1f} pts")
print(f"  SL Hit Rate:           {(loss_count/total*100) if total else 0:.1f}%")
if losses:
    biggest_sl = min(losses, key=lambda t: t['points'])
    print(f"  Biggest SL:            {biggest_sl['symbol']} {biggest_sl['points']:+.1f} pts @ {biggest_sl['entry']}")

print(f"\n{'='*40}")
print(f"  PER-SYMBOL BREAKDOWN")
print(f"{'='*40}")
print(f"  {'Symbol':8s} {'Trades':>6s} {'Wins':>5s} {'Loss':>5s} {'BE':>3s} {'WR%':>6s} {'Pts Won':>8s} {'Pts Lost':>9s} {'Net $':>10s}")
print(f"  {'-'*8} {'-'*6} {'-'*5} {'-'*5} {'-'*3} {'-'*6} {'-'*8} {'-'*9} {'-'*10}")
for sym, s in sorted(sym_stats.items(), key=lambda x: x[1]['dollar_pnl'], reverse=True):
    wr = (s['wins'] / (s['wins']+s['losses']) * 100) if (s['wins']+s['losses']) > 0 else 0
    print(f"  {sym:8s} {s['total']:6d} {s['wins']:5d} {s['losses']:5d} {s['be']:3d} {wr:5.1f}% {s['pts_won']:+7.1f} {s['pts_lost']:+8.1f} ${s['dollar_pnl']:+9.2f}")

print(f"\n{'='*40}")
print(f"  ALL TRADES (chronological)")
print(f"{'='*40}")
print(f"  {'#':>3s} {'Date':10s} {'Time':5s} {'Symbol':8s} {'Dir':5s} {'Entry':>8s} {'SL':>8s} {'Result':6s} {'Points':>8s} {'$P&L':>10s}")
print(f"  {'-'*3} {'-'*10} {'-'*5} {'-'*8} {'-'*5} {'-'*8} {'-'*8} {'-'*6} {'-'*8} {'-'*10}")
for i, t in enumerate(trades, 1):
    dt = datetime.fromisoformat(t['time'].replace('Z', '+00:00'))
    result_icon = 'WIN' if t['exit_type'] == 'WIN' else ('SL' if t['exit_type'] == 'SL' else ('BE' if t['exit_type'] == 'BE' else 'EXIT'))
    print(f"  {i:3d} {dt.strftime('%Y-%m-%d'):10s} {dt.strftime('%H:%M'):5s} "
          f"{t['symbol']:8s} {t['direction']:5s} {t['entry']:>8.1f} {t['stoploss']:>8.1f} "
          f"{result_icon:6s} {t['points']:>+7.1f} ${t['dollar_pnl']:>+9.2f}")

if open_positions:
    print(f"\n  OPEN POSITIONS ({len(open_positions)}):")
    for p in open_positions:
        dt = datetime.fromisoformat(p['time'].replace('Z', '+00:00'))
        print(f"  {dt.strftime('%Y-%m-%d %H:%M'):16s} {p['symbol']:8s} {p['direction']:5s} @ {p['entry']:.1f} SL:{p['stoploss']:.1f}")

print("\n" + "="*75)
