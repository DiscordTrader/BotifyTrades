"""
Fetch last 1000 messages from a Discord channel and analyze trading signals.
Usage: python scripts/analyze_channel.py <channel_id>
"""
import sys, os, json, re, time
os.environ['PYTHONIOENCODING'] = 'utf-8'
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from datetime import datetime
from collections import defaultdict

CHANNEL_ID = sys.argv[1] if len(sys.argv) > 1 else '1251181965252755517'
MAX_MESSAGES = 1000

def get_discord_token():
    # Try encrypted DB credentials
    try:
        from gui_app.config_service import load_config
        discord_creds = load_config('discord_credentials')
        if discord_creds and discord_creds.get('token'):
            return discord_creds['token'].strip()
    except Exception as e:
        print(f"DB creds error: {e}")

    # Try startup credentials
    try:
        from gui_app.broker_credentials_service import get_all_credentials_for_startup
        creds = get_all_credentials_for_startup()
        token = creds.get('DISCORD_USER_TOKEN', '').strip()
        if token:
            return token
    except Exception:
        pass

    # Try env / config.ini
    token = os.getenv('DISCORD_USER_TOKEN', '').strip()
    if token:
        return token
    try:
        import configparser
        cfg = configparser.ConfigParser()
        cfg.read('config.ini')
        return cfg['discord'].get('discord_user_token', '').strip()
    except Exception:
        pass
    return None

def fetch_messages(token, channel_id, limit=1000):
    headers = {'Authorization': token, 'Content-Type': 'application/json'}
    messages = []
    before = None
    while len(messages) < limit:
        batch = min(100, limit - len(messages))
        url = f'https://discord.com/api/v9/channels/{channel_id}/messages?limit={batch}'
        if before:
            url += f'&before={before}'
        resp = httpx.get(url, headers=headers, timeout=15)
        if resp.status_code == 429:
            retry_after = resp.json().get('retry_after', 5)
            print(f"Rate limited, waiting {retry_after}s...")
            time.sleep(retry_after)
            continue
        if resp.status_code != 200:
            print(f"Error {resp.status_code}: {resp.text[:200]}")
            break
        data = resp.json()
        if not data:
            break
        messages.extend(data)
        before = data[-1]['id']
        print(f"Fetched {len(messages)} messages...")
        time.sleep(0.5)
    return messages

def parse_signal(content):
    """Parse BTO/STC signals from message content.
    Formats:
      BTO 3 ORCL 200C 12/26 @ 2.61
      STC 3 ORCL 200C 12/26 @ 3.50
      BTO 5 SPY @ 450.00  (stock)
      SL hit / stopped out patterns
    """
    if not content:
        return None
    content = content.strip()

    # Remove common prefixes/noise
    for prefix in ['[TEST] ', '[CANCELED] ', '🔴 ', '🟢 ', '📊 ', '💰 ', '⚡ ', '🎯 ']:
        content = content.replace(prefix, '')

    # Match: BTO/STC qty SYMBOL strike_direction expiry @ price
    # Options: BTO 3 ORCL 200C 12/26 @ 2.61
    opt_pat = re.compile(
        r'(BTO|STC|BUY|SELL)\s+(\d+)\s+([A-Z]{1,5})\s+'
        r'(\d+(?:\.\d+)?)\s*([CP])\s+'
        r'(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s*'
        r'(?:@|at)\s*\$?(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    m = opt_pat.search(content)
    if m:
        action = m.group(1).upper()
        if action == 'BUY': action = 'BTO'
        if action == 'SELL': action = 'STC'
        return {
            'action': action,
            'qty': int(m.group(2)),
            'symbol': m.group(3).upper(),
            'strike': float(m.group(4)),
            'direction': m.group(5).upper(),
            'expiry': m.group(6),
            'price': float(m.group(7)),
            'asset_type': 'option',
        }

    # Stock: BTO 5 SPY @ 450.00
    stock_pat = re.compile(
        r'(BTO|STC|BUY|SELL)\s+(\d+)\s+([A-Z]{1,5})\s*'
        r'(?:@|at)\s*\$?(\d+(?:\.\d+)?)',
        re.IGNORECASE
    )
    m = stock_pat.search(content)
    if m:
        action = m.group(1).upper()
        if action == 'BUY': action = 'BTO'
        if action == 'SELL': action = 'STC'
        return {
            'action': action,
            'qty': int(m.group(2)),
            'symbol': m.group(3).upper(),
            'price': float(m.group(4)),
            'asset_type': 'stock',
        }

    # SL / stop loss patterns
    sl_pat = re.compile(
        r'(?:SL|stop\s*loss|stopped?\s*out)\s+.*?([A-Z]{1,5})\s*'
        r'(?:@|at)?\s*\$?(\d+(?:\.\d+)?)?',
        re.IGNORECASE
    )
    m = sl_pat.search(content)
    if m:
        return {
            'action': 'SL',
            'symbol': m.group(1).upper(),
            'price': float(m.group(2)) if m.group(2) else None,
            'asset_type': 'unknown',
        }

    return None

def match_trades(signals):
    """Match BTO entries with STC/SL exits to form complete trades."""
    open_positions = defaultdict(list)  # key -> list of (signal, msg_time)
    trades = []

    for sig, msg_time, raw_content in signals:
        action = sig['action']
        symbol = sig['symbol']

        if sig['asset_type'] == 'option':
            key = f"{symbol}_{sig.get('strike','')}_{sig.get('direction','')}_{sig.get('expiry','')}"
        else:
            key = f"{symbol}_stock"

        if action == 'BTO':
            open_positions[key].append((sig, msg_time, raw_content))
        elif action in ('STC', 'SL'):
            if open_positions[key]:
                entry_sig, entry_time, entry_raw = open_positions[key].pop(0)
                entry_price = entry_sig['price']
                exit_price = sig['price'] if sig.get('price') else 0
                entry_qty = entry_sig.get('qty', 1)
                exit_qty = sig.get('qty', entry_qty)

                if entry_sig['asset_type'] == 'option':
                    pnl = (exit_price - entry_price) * min(entry_qty, exit_qty) * 100
                else:
                    pnl = (exit_price - entry_price) * min(entry_qty, exit_qty)

                pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

                trades.append({
                    'symbol': symbol,
                    'key': key,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'qty': min(entry_qty, exit_qty),
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'entry_time': entry_time,
                    'exit_time': msg_time,
                    'exit_type': 'SL' if action == 'SL' else 'STC',
                    'asset_type': entry_sig['asset_type'],
                    'is_win': pnl > 0,
                    'strike': entry_sig.get('strike'),
                    'direction': entry_sig.get('direction'),
                    'expiry': entry_sig.get('expiry'),
                })

    # Remaining open positions
    still_open = []
    for key, entries in open_positions.items():
        for sig, t, raw in entries:
            still_open.append({'key': key, 'signal': sig, 'time': t})

    return trades, still_open

def analyze(trades, still_open, all_signals):
    total = len(trades)
    if total == 0:
        print("\n=== NO COMPLETED TRADES FOUND ===")
        print(f"Total signals parsed: {len(all_signals)}")
        print(f"Still open positions: {len(still_open)}")
        return

    wins = [t for t in trades if t['is_win']]
    losses = [t for t in trades if not t['is_win']]
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / total * 100) if total > 0 else 0

    total_pnl = sum(t['pnl'] for t in trades)
    total_win_pnl = sum(t['pnl'] for t in wins)
    total_loss_pnl = sum(t['pnl'] for t in losses)
    avg_win = (total_win_pnl / win_count) if win_count > 0 else 0
    avg_loss = (total_loss_pnl / loss_count) if loss_count > 0 else 0
    profit_factor = abs(total_win_pnl / total_loss_pnl) if total_loss_pnl != 0 else float('inf')

    best_trade = max(trades, key=lambda t: t['pnl'])
    worst_trade = min(trades, key=lambda t: t['pnl'])

    avg_win_pct = (sum(t['pnl_pct'] for t in wins) / win_count) if win_count > 0 else 0
    avg_loss_pct = (sum(t['pnl_pct'] for t in losses) / loss_count) if loss_count > 0 else 0

    # SL vs manual exits
    sl_exits = [t for t in trades if t['exit_type'] == 'SL']
    manual_exits = [t for t in trades if t['exit_type'] == 'STC']

    # Per-symbol breakdown
    symbol_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'pnl': 0, 'trades': 0})
    for t in trades:
        s = symbol_stats[t['symbol']]
        s['trades'] += 1
        s['pnl'] += t['pnl']
        if t['is_win']:
            s['wins'] += 1
        else:
            s['losses'] += 1

    # Streak analysis
    max_win_streak = 0
    max_loss_streak = 0
    cur_streak = 0
    last_was_win = None
    for t in sorted(trades, key=lambda x: x['entry_time']):
        if t['is_win']:
            if last_was_win:
                cur_streak += 1
            else:
                cur_streak = 1
            max_win_streak = max(max_win_streak, cur_streak)
            last_was_win = True
        else:
            if not last_was_win and last_was_win is not None:
                cur_streak += 1
            else:
                cur_streak = 1
            max_loss_streak = max(max_loss_streak, cur_streak)
            last_was_win = False

    # Options vs stocks
    opt_trades = [t for t in trades if t['asset_type'] == 'option']
    stock_trades = [t for t in trades if t['asset_type'] == 'stock']

    print("\n" + "="*70)
    print(f"   CHANNEL SIGNAL ANALYSIS — {CHANNEL_ID}")
    print("="*70)
    print(f"\n📊 OVERVIEW")
    print(f"   Messages fetched:     {len(all_signals)} signals parsed from messages")
    print(f"   Completed trades:     {total}")
    print(f"   Still open:           {len(still_open)}")
    print(f"   Option trades:        {len(opt_trades)}")
    print(f"   Stock trades:         {len(stock_trades)}")

    print(f"\n🎯 WIN RATE")
    print(f"   Wins:                 {win_count}")
    print(f"   Losses:               {loss_count}")
    print(f"   Win Rate:             {win_rate:.1f}%")
    print(f"   Max Win Streak:       {max_win_streak}")
    print(f"   Max Loss Streak:      {max_loss_streak}")

    print(f"\n💰 P&L SUMMARY")
    print(f"   Total P&L:            ${total_pnl:,.2f}")
    print(f"   Total Wins:           ${total_win_pnl:,.2f}")
    print(f"   Total Losses:         ${total_loss_pnl:,.2f}")
    print(f"   Avg Win:              ${avg_win:,.2f} ({avg_win_pct:+.1f}%)")
    print(f"   Avg Loss:             ${avg_loss:,.2f} ({avg_loss_pct:+.1f}%)")
    print(f"   Profit Factor:        {profit_factor:.2f}")
    print(f"   Best Trade:           {best_trade['symbol']} ${best_trade['pnl']:+,.2f} ({best_trade['pnl_pct']:+.1f}%)")
    print(f"   Worst Trade:          {worst_trade['symbol']} ${worst_trade['pnl']:+,.2f} ({worst_trade['pnl_pct']:+.1f}%)")

    if sl_exits:
        sl_pnl = sum(t['pnl'] for t in sl_exits)
        print(f"\n🛑 STOP LOSS ANALYSIS")
        print(f"   SL Exits:             {len(sl_exits)}")
        print(f"   SL Total P&L:         ${sl_pnl:,.2f}")
        print(f"   Avg SL Loss:          ${sl_pnl/len(sl_exits):,.2f}")

    print(f"\n📈 TOP SYMBOLS (by P&L)")
    sorted_symbols = sorted(symbol_stats.items(), key=lambda x: x[1]['pnl'], reverse=True)
    for sym, stats in sorted_symbols[:15]:
        wr = (stats['wins'] / stats['trades'] * 100) if stats['trades'] > 0 else 0
        print(f"   {sym:6s}  {stats['trades']:3d} trades  W:{stats['wins']:2d}  L:{stats['losses']:2d}  WR:{wr:5.1f}%  P&L: ${stats['pnl']:+,.2f}")

    if sorted_symbols and len(sorted_symbols) > 15:
        print(f"   ... and {len(sorted_symbols)-15} more symbols")

    if still_open:
        print(f"\n📌 OPEN POSITIONS ({len(still_open)})")
        for pos in still_open[:10]:
            sig = pos['signal']
            t = pos['time']
            label = f"{sig['symbol']}"
            if sig['asset_type'] == 'option':
                label += f" {sig.get('strike','')}{sig.get('direction','')} {sig.get('expiry','')}"
            print(f"   {label:25s}  {sig.get('qty',1)}x @ ${sig['price']:.2f}  ({t})")
        if len(still_open) > 10:
            print(f"   ... and {len(still_open)-10} more")

    # Individual trades list
    print(f"\n📋 ALL TRADES (chronological)")
    print(f"   {'Symbol':8s} {'Type':6s} {'Entry':>8s} {'Exit':>8s} {'Qty':>4s} {'P&L':>10s} {'%':>7s} {'Exit':4s} {'Time'}")
    print(f"   {'-'*8} {'-'*6} {'-'*8} {'-'*8} {'-'*4} {'-'*10} {'-'*7} {'-'*4} {'-'*20}")
    for t in sorted(trades, key=lambda x: x['entry_time']):
        sym = t['symbol']
        if t['asset_type'] == 'option':
            sym += f" {int(t['strike']) if t.get('strike') else ''}{t.get('direction','')}"
        print(f"   {sym:8s} {'OPT' if t['asset_type']=='option' else 'STK':6s} "
              f"${t['entry_price']:>7.2f} ${t['exit_price']:>7.2f} {t['qty']:>4d} "
              f"${t['pnl']:>+9.2f} {t['pnl_pct']:>+6.1f}% {t['exit_type']:4s} {t['entry_time'][:16]}")

    print("\n" + "="*70)


def main():
    token = get_discord_token()
    if not token:
        print("ERROR: Could not find Discord token")
        sys.exit(1)

    print(f"Fetching last {MAX_MESSAGES} messages from channel {CHANNEL_ID}...")
    messages = fetch_messages(token, CHANNEL_ID, MAX_MESSAGES)
    print(f"Total messages fetched: {len(messages)}")

    # Save raw messages for reference
    with open('scripts/channel_messages.json', 'w', encoding='utf-8') as f:
        json.dump(messages, f, indent=2, ensure_ascii=False)
    print(f"Saved raw messages to scripts/channel_messages.json")

    # Parse signals (process oldest first)
    messages.reverse()
    all_signals = []
    unparsed = []
    for msg in messages:
        content = msg.get('content', '')
        if not content.strip():
            continue
        ts = msg.get('timestamp', '')
        sig = parse_signal(content)
        if sig:
            all_signals.append((sig, ts, content))
        else:
            unparsed.append(content)

    print(f"Parsed {len(all_signals)} signals, {len(unparsed)} non-signal messages")

    # Match entries to exits
    trades, still_open = match_trades(all_signals)

    # Analyze
    analyze(trades, still_open, all_signals)

    # Show sample unparsed for debugging
    if unparsed:
        print(f"\n📝 SAMPLE NON-SIGNAL MESSAGES (first 10):")
        for msg in unparsed[:10]:
            print(f"   {msg[:100]}")


if __name__ == '__main__':
    main()
