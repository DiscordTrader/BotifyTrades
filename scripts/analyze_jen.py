"""Analyze jen-selling channel — SPX credit spread trades."""
import json, re, sys, glob
from datetime import datetime
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

files = glob.glob('extracted_*jen-selling*')
if not files:
    print("No jen-selling JSON found"); sys.exit(1)

with open(files[0], 'r', encoding='utf-8') as f:
    data = json.load(f)

msgs = [m for m in data['messages'] if m['author_name'] == 'the.wild.angel']
msgs.sort(key=lambda m: m['timestamp'])

entries = []
exits = []
recaps = []

def strip_md(text):
    """Strip discord markdown (*, _, ~) for clean parsing."""
    return re.sub(r'[*_~]+', '', text)

# --- PARSE ENTRIES ---
entry_pat = re.compile(r'(Day Trade Alert|Swing Trade Alert|Trade Alert)', re.IGNORECASE)
pos_pat = re.compile(r'Position\s*:?\s*((?:SPX|AVGO|META|AAPL|TSLA|AMZN|GOOGL|NVDA)\s+(?:PCS|CCS)\s+[\d]+/[\d]+(?:\s+\S+)?)', re.IGNORECASE)
entry_price_pat = re.compile(r'Entry\s*:?\s*\$?([\d]+\.[\d]+)', re.IGNORECASE)

for m in msgs:
    raw = m.get('content', '')
    if not entry_pat.search(raw):
        continue
    c = strip_md(raw)
    pos_match = pos_pat.search(c)
    if not pos_match:
        continue
    position = pos_match.group(1).strip()

    price_match = entry_price_pat.search(c)
    entry_credit = None
    if price_match:
        try:
            entry_credit = float(price_match.group(1))
        except ValueError:
            pass

    if not entry_credit:
        range_pat = re.compile(r'Entry\s*:?\s*\$?([\d]+\.[\d]+)[-–]([\d]+\.[\d]+)', re.IGNORECASE)
        rm = range_pat.search(c)
        if rm:
            try:
                entry_credit = (float(rm.group(1)) + float(rm.group(2))) / 2
            except ValueError:
                pass

    if not entry_credit:
        cm = re.search(r'([\d]+\.[\d]+)\s*credit', c, re.IGNORECASE)
        if cm:
            entry_credit = float(cm.group(1))

    trade_type = 'day'
    if 'swing' in raw.lower():
        trade_type = 'swing'

    spread_type = 'PCS' if 'PCS' in position.upper() else 'CCS'
    ticker = position.split()[0]

    entries.append({
        'timestamp': m['timestamp'],
        'position': position,
        'entry_credit': entry_credit,
        'trade_type': trade_type,
        'spread_type': spread_type,
        'ticker': ticker,
        'msg_id': m['id'],
    })

# --- PARSE EXITS ---
exit_pat = re.compile(r'(Trade Exit|Trade Expiry|Trade Stopped)', re.IGNORECASE)
result_pct_pat = re.compile(r'Result\s*:?\s*[+]?\s*(\d+)%\s*(profit|gain)', re.IGNORECASE)
loss_pct_pat = re.compile(r'🔻\s*(\d+)%')
exit_price_pat = re.compile(r'Exit Price\s*:?\s*\$?([\d]+\.[\d]+)', re.IGNORECASE)

for m in msgs:
    raw = m.get('content', '')
    if not exit_pat.search(raw):
        continue
    c = strip_md(raw)
    pos_match = pos_pat.search(c)
    if not pos_match:
        continue
    position = pos_match.group(1).strip()

    is_loss = '❌' in raw
    result_pct = None

    rm = result_pct_pat.search(c)
    if rm:
        result_pct = float(rm.group(1))

    lm = loss_pct_pat.search(raw)
    if lm:
        result_pct = float(lm.group(1))
        is_loss = True

    # Pattern: -XX% loss on capital (no emoji)
    loss_text_pat = re.search(r'-\s*([\d.]+)%\s*loss', c, re.IGNORECASE)
    if loss_text_pat:
        result_pct = float(loss_text_pat.group(1))
        is_loss = True

    # "Max Loss" = 100% loss on capital
    if re.search(r'Max Loss', c, re.IGNORECASE) and not result_pct:
        result_pct = 100.0
        is_loss = True

    is_win = not is_loss

    exit_price = None
    ep = exit_price_pat.search(c)
    if ep:
        exit_price = float(ep.group(1))

    is_expiry = 'expiry' in raw.lower() or 'expired' in raw.lower()

    exits.append({
        'timestamp': m['timestamp'],
        'position': position,
        'result_pct': result_pct,
        'is_win': is_win,
        'exit_price': exit_price,
        'is_expiry': is_expiry,
        'msg_id': m['id'],
    })

# --- PARSE WEEKLY RECAPS (for validation) ---
recap_pat = re.compile(r'Weekly Trade Recap', re.IGNORECASE)
for m in msgs:
    raw = m.get('content', '')
    if not recap_pat.search(raw):
        continue
    c = strip_md(raw)
    total_m = re.search(r'Total Trades[^:]*:\s*(\d+)', c, re.IGNORECASE)
    wins_m = re.search(r'Wins\s*:?\s*(\d+)', c, re.IGNORECASE)
    losses_m = re.search(r'Losses\s*:?\s*(\d+)', c, re.IGNORECASE)
    wr_m = re.search(r'Win Rate\s*:?\s*([\d.]+)%', c, re.IGNORECASE)
    pl_m = re.search(r'P/L[^:]*:\s*[✅❌\s]*\$?([\d,]+)', c, re.IGNORECASE)

    week_m = re.search(r'For\s+(\w+\s+\d+[-–]\d+)', c, re.IGNORECASE)
    week_label = week_m.group(1) if week_m else m['timestamp'][:10]

    w = int(wins_m.group(1)) if wins_m else 0
    l = int(losses_m.group(1)) if losses_m else 0
    t = int(total_m.group(1)) if total_m else (w + l)
    if t == 0 and (w + l) > 0:
        t = w + l

    recaps.append({
        'week': week_label,
        'total': t,
        'wins': w,
        'losses': l,
        'win_rate': float(wr_m.group(1)) if wr_m else (w/t*100 if t else 0),
        'pl': float(pl_m.group(1).replace(',', '')) if pl_m else None,
        'timestamp': m['timestamp'],
    })

# --- MATCH ENTRIES TO EXITS ---
def normalize_pos(pos):
    """Normalize position for matching: 'SPX PCS 7340/7330' (drop date/DTE)"""
    parts = pos.split()
    if len(parts) >= 3:
        return ' '.join(parts[:3]).upper()
    return pos.upper()

def get_spread_width(pos):
    """Extract spread width from strikes like '7340/7330' → 10"""
    m = re.search(r'(\d+)/(\d+)', pos)
    if m:
        return abs(int(m.group(1)) - int(m.group(2)))
    return 10

used_exits = set()
matched_trades = []
unmatched_entries = []
unmatched_exits = []

for entry in entries:
    entry_norm = normalize_pos(entry['position'])
    entry_ts = entry['timestamp']

    best_exit = None
    best_idx = None
    for i, ex in enumerate(exits):
        if i in used_exits:
            continue
        ex_norm = normalize_pos(ex['position'])
        if entry_norm == ex_norm and ex['timestamp'] > entry_ts:
            if best_exit is None or ex['timestamp'] < best_exit['timestamp']:
                best_exit = ex
                best_idx = i

    if best_exit:
        used_exits.add(best_idx)

        # Calculate dollar P&L per contract
        pnl_per_contract = None
        if entry['entry_credit'] and best_exit['exit_price'] is not None:
            pnl_per_contract = (entry['entry_credit'] - best_exit['exit_price']) * 100
        elif entry['entry_credit'] and best_exit['is_expiry']:
            pnl_per_contract = entry['entry_credit'] * 100
        elif entry['entry_credit'] and best_exit['result_pct'] is not None:
            if best_exit['is_win']:
                pnl_per_contract = entry['entry_credit'] * (best_exit['result_pct'] / 100) * 100
            else:
                # "% loss on capital" = % of max risk (spread_width - credit)
                sw = get_spread_width(entry['position'])
                max_risk = (sw - entry['entry_credit']) * 100
                pnl_per_contract = -(max_risk * best_exit['result_pct'] / 100)

        matched_trades.append({
            'position': entry['position'],
            'ticker': entry['ticker'],
            'spread_type': entry['spread_type'],
            'trade_type': entry['trade_type'],
            'entry_credit': entry['entry_credit'],
            'exit_price': best_exit['exit_price'],
            'result_pct': best_exit['result_pct'],
            'is_win': best_exit['is_win'],
            'is_expiry': best_exit['is_expiry'],
            'pnl_per_contract': pnl_per_contract,
            'entry_time': entry['timestamp'],
            'exit_time': best_exit['timestamp'],
        })
    else:
        unmatched_entries.append(entry)

for i, ex in enumerate(exits):
    if i not in used_exits:
        unmatched_exits.append(ex)

# Also treat unmatched exits as standalone trades (they have results)
standalone_trades = []
for ex in unmatched_exits:
    standalone_trades.append({
        'position': ex['position'],
        'ticker': ex['position'].split()[0] if ex['position'] else 'SPX',
        'spread_type': 'PCS' if 'PCS' in ex['position'].upper() else 'CCS',
        'trade_type': 'unknown',
        'entry_credit': None,
        'exit_price': ex['exit_price'],
        'result_pct': ex['result_pct'],
        'is_win': ex['is_win'],
        'is_expiry': ex['is_expiry'],
        'pnl_per_contract': -(1000 * ex['result_pct'] / 100) if (not ex['is_win'] and ex['result_pct']) else None,
        'entry_time': None,
        'exit_time': ex['timestamp'],
    })

all_trades = matched_trades + standalone_trades

# --- ANALYSIS ---
print("=" * 70)
print("  JEN-SELLING CHANNEL ANALYSIS — SPX Credit Spreads")
print("=" * 70)
print(f"\nData source: {files[0]}")
print(f"Messages analyzed: {len(msgs)} (from {data['message_count']} total)")
print(f"Date range: {msgs[0]['timestamp'][:10]} to {msgs[-1]['timestamp'][:10]}")

print(f"\n--- PARSING RESULTS ---")
print(f"Entry alerts found: {len(entries)}")
print(f"Exit messages found: {len(exits)}")
print(f"Matched entry→exit pairs: {len(matched_trades)}")
print(f"Unmatched exits (standalone): {len(standalone_trades)}")
print(f"Unmatched entries (no exit found): {len(unmatched_entries)}")
print(f"Weekly recaps found: {len(recaps)}")

print(f"\n{'=' * 70}")
print(f"  TRADE PERFORMANCE SUMMARY")
print(f"{'=' * 70}")

total = len(all_trades)
wins = [t for t in all_trades if t['is_win']]
losses = [t for t in all_trades if not t['is_win']]

print(f"\nTotal closed trades: {total}")
print(f"Wins: {len(wins)}")
print(f"Losses: {len(losses)}")
print(f"Win Rate: {len(wins)/total*100:.1f}%" if total else "N/A")

# Result percentages
win_pcts = [t['result_pct'] for t in wins if t['result_pct'] is not None]
loss_pcts = [t['result_pct'] for t in losses if t['result_pct'] is not None]

if win_pcts:
    print(f"\nAvg Win %: {sum(win_pcts)/len(win_pcts):.1f}%")
    print(f"Median Win %: {sorted(win_pcts)[len(win_pcts)//2]:.1f}%")
    print(f"Best Win: {max(win_pcts):.0f}%")
    print(f"Worst Win: {min(win_pcts):.0f}%")

if loss_pcts:
    print(f"\nAvg Loss %: {sum(loss_pcts)/len(loss_pcts):.1f}%")
    print(f"Worst Loss: {max(loss_pcts):.0f}%")
    print(f"Smallest Loss: {min(loss_pcts):.0f}%")

# Dollar P&L (matched trades only)
pnl_trades = [t for t in matched_trades if t['pnl_per_contract'] is not None]
if pnl_trades:
    total_pnl = sum(t['pnl_per_contract'] for t in pnl_trades)
    win_pnl = sum(t['pnl_per_contract'] for t in pnl_trades if t['is_win'])
    loss_pnl = sum(t['pnl_per_contract'] for t in pnl_trades if not t['is_win'])
    avg_win_pnl = win_pnl / len([t for t in pnl_trades if t['is_win']]) if any(t['is_win'] for t in pnl_trades) else 0
    avg_loss_pnl = loss_pnl / len([t for t in pnl_trades if not t['is_win']]) if any(not t['is_win'] for t in pnl_trades) else 0

    print(f"\n--- DOLLAR P&L (per 1 contract, matched trades only: {len(pnl_trades)}) ---")
    print(f"Total P&L: ${total_pnl:+,.2f}")
    print(f"Total Wins: ${win_pnl:+,.2f}")
    print(f"Total Losses: ${loss_pnl:+,.2f}")
    print(f"Avg Win: ${avg_win_pnl:+,.2f}")
    print(f"Avg Loss: ${avg_loss_pnl:+,.2f}")
    if loss_pnl != 0:
        print(f"Profit Factor: {abs(win_pnl/loss_pnl):.2f}")

# --- BY SPREAD TYPE ---
print(f"\n{'=' * 70}")
print(f"  BY SPREAD TYPE")
print(f"{'=' * 70}")

for stype in ['PCS', 'CCS']:
    st_trades = [t for t in all_trades if t['spread_type'] == stype]
    if not st_trades:
        continue
    st_wins = [t for t in st_trades if t['is_win']]
    st_losses = [t for t in st_trades if not t['is_win']]
    st_wr = len(st_wins) / len(st_trades) * 100 if st_trades else 0

    st_label = "Put Credit Spread (bullish)" if stype == 'PCS' else "Call Credit Spread (bearish)"
    print(f"\n{stype} — {st_label}")
    print(f"  Trades: {len(st_trades)}  |  Wins: {len(st_wins)}  |  Losses: {len(st_losses)}  |  WR: {st_wr:.1f}%")

    st_pnl = [t for t in st_trades if t in matched_trades and t.get('pnl_per_contract') is not None]
    if st_pnl:
        print(f"  P&L: ${sum(t['pnl_per_contract'] for t in st_pnl):+,.2f}")

# --- BY TRADE TYPE ---
print(f"\n{'=' * 70}")
print(f"  BY TRADE TYPE")
print(f"{'=' * 70}")

for ttype in ['day', 'swing']:
    tt_trades = [t for t in all_trades if t['trade_type'] == ttype]
    if not tt_trades:
        continue
    tt_wins = [t for t in tt_trades if t['is_win']]
    tt_wr = len(tt_wins) / len(tt_trades) * 100 if tt_trades else 0
    print(f"\n{ttype.upper()} TRADES")
    print(f"  Trades: {len(tt_trades)}  |  Wins: {len(tt_wins)}  |  Losses: {len(tt_trades)-len(tt_wins)}  |  WR: {tt_wr:.1f}%")

# --- BY TICKER ---
tickers = set(t['ticker'] for t in all_trades)
if len(tickers) > 1:
    print(f"\n{'=' * 70}")
    print(f"  BY TICKER")
    print(f"{'=' * 70}")
    for tk in sorted(tickers):
        tk_trades = [t for t in all_trades if t['ticker'] == tk]
        tk_wins = [t for t in tk_trades if t['is_win']]
        tk_wr = len(tk_wins) / len(tk_trades) * 100 if tk_trades else 0
        print(f"  {tk}: {len(tk_trades)} trades, {len(tk_wins)} wins, WR {tk_wr:.1f}%")

# --- BY MONTH ---
print(f"\n{'=' * 70}")
print(f"  MONTHLY BREAKDOWN")
print(f"{'=' * 70}")

monthly = defaultdict(lambda: {'wins': 0, 'losses': 0, 'pnl': 0.0})
for t in all_trades:
    ts = t.get('exit_time') or t.get('entry_time') or ''
    if not ts:
        continue
    month_key = ts[:7]  # YYYY-MM
    if t['is_win']:
        monthly[month_key]['wins'] += 1
    else:
        monthly[month_key]['losses'] += 1
    if t.get('pnl_per_contract'):
        monthly[month_key]['pnl'] += t['pnl_per_contract']

print(f"\n{'Month':<10} {'Trades':>7} {'Wins':>6} {'Losses':>7} {'WR':>7} {'P&L':>10}")
print("-" * 50)
for month in sorted(monthly.keys()):
    d = monthly[month]
    total_m = d['wins'] + d['losses']
    wr = d['wins'] / total_m * 100 if total_m else 0
    pnl_str = f"${d['pnl']:+,.0f}" if d['pnl'] != 0 else "—"
    print(f"{month:<10} {total_m:>7} {d['wins']:>6} {d['losses']:>7} {wr:>6.1f}% {pnl_str:>10}")

# --- WEEKLY RECAPS (self-reported) ---
if recaps:
    print(f"\n{'=' * 70}")
    print(f"  WEEKLY RECAPS (Jen's Self-Reported)")
    print(f"{'=' * 70}")

    recap_total_trades = 0
    recap_total_wins = 0
    recap_total_losses = 0
    recap_total_pnl = 0

    print(f"\n{'Week':<20} {'Trades':>7} {'Wins':>6} {'Losses':>7} {'WR':>7} {'P&L':>10}")
    print("-" * 60)
    for r in sorted(recaps, key=lambda x: x['timestamp']):
        t = r['total'] or 0
        w = r['wins'] or 0
        l = r['losses'] or 0
        wr = r['win_rate'] or (w/t*100 if t else 0)
        pl = r['pl'] or 0
        recap_total_trades += t
        recap_total_wins += w
        recap_total_losses += l
        recap_total_pnl += pl
        print(f"{r['week']:<20} {t:>7} {w:>6} {l:>7} {wr:>6.1f}% {'$'+str(int(pl)):>10}")

    print("-" * 60)
    recap_wr = recap_total_wins / recap_total_trades * 100 if recap_total_trades else 0
    print(f"{'TOTAL':<20} {recap_total_trades:>7} {recap_total_wins:>6} {recap_total_losses:>7} {recap_wr:>6.1f}% {'$'+str(int(recap_total_pnl)):>10}")

# --- STREAK ANALYSIS ---
print(f"\n{'=' * 70}")
print(f"  STREAK ANALYSIS")
print(f"{'=' * 70}")

max_win_streak = 0
max_loss_streak = 0
cur_streak = 0
cur_type = None

sorted_trades = sorted(all_trades, key=lambda t: t.get('exit_time') or t.get('entry_time') or '')
for t in sorted_trades:
    if t['is_win']:
        if cur_type == 'win':
            cur_streak += 1
        else:
            cur_type = 'win'
            cur_streak = 1
        max_win_streak = max(max_win_streak, cur_streak)
    else:
        if cur_type == 'loss':
            cur_streak += 1
        else:
            cur_type = 'loss'
            cur_streak = 1
        max_loss_streak = max(max_loss_streak, cur_streak)

print(f"Max Win Streak: {max_win_streak}")
print(f"Max Loss Streak: {max_loss_streak}")

# Expiry stats
expiry_trades = [t for t in all_trades if t.get('is_expiry')]
print(f"\nExpired Worthless (100% profit): {len(expiry_trades)}")
print(f"  % of all trades: {len(expiry_trades)/total*100:.1f}%" if total else "")

# --- RECENT TRADES LIST ---
print(f"\n{'=' * 70}")
print(f"  LAST 20 TRADES (most recent first)")
print(f"{'=' * 70}")

recent = sorted(all_trades, key=lambda t: t.get('exit_time') or t.get('entry_time') or '', reverse=True)[:20]
print(f"\n{'Date':<12} {'Position':<25} {'Type':<5} {'Entry':>6} {'Exit':>6} {'Result':>8} {'P&L':>8}")
print("-" * 75)
for t in recent:
    ts = (t.get('exit_time') or '')[:10]
    pos = t['position'][:24]
    stype = t['spread_type']
    entry = f"${t['entry_credit']:.2f}" if t.get('entry_credit') else "—"
    exit_p = f"${t['exit_price']:.2f}" if t.get('exit_price') else ("EXP" if t.get('is_expiry') else "—")

    if t['is_win']:
        result = f"+{t['result_pct']:.0f}%" if t.get('result_pct') else "WIN"
    else:
        result = f"-{t['result_pct']:.0f}%" if t.get('result_pct') else "LOSS"

    pnl = f"${t['pnl_per_contract']:+,.0f}" if t.get('pnl_per_contract') else "—"
    print(f"{ts:<12} {pos:<25} {stype:<5} {entry:>6} {exit_p:>6} {result:>8} {pnl:>8}")

print(f"\n{'=' * 70}")
print("  NOTE: P&L calculated per 1 contract. Credit spreads are $10 wide.")
print("  Win/Loss % = percentage of credit kept or lost.")
print("  Her standard sizing: $1,000 risk per spread (1 contract).")
print(f"{'=' * 70}")
