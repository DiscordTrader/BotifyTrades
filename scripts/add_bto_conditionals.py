"""Parse BTO signals from extracted JSON and add as conditional orders."""
import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['PYTHONIOENCODING'] = 'utf-8'

with open('extracted_botifytrades-ai_20260528_190000.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

bto_signals = []
for msg in data['messages']:
    for embed in msg.get('embeds', []):
        title = embed.get('title', '')
        if 'BTO' not in title:
            continue
        m = re.search(r'BTO\s+(\w+)\s+over\s+\$?([\d.]+)', title)
        if not m:
            continue
        symbol = m.group(1)
        trigger = float(m.group(2))

        sl_price = None
        for field in embed.get('fields', []):
            if 'Stop Loss' in field.get('name', ''):
                sl_match = re.search(r'\*\*\$?([\d.]+)\*\*', field.get('value', ''))
                if sl_match:
                    sl_price = float(sl_match.group(1))
                break

        catalyst = ''
        for field in embed.get('fields', []):
            if 'Catalyst' in field.get('name', ''):
                catalyst = field.get('value', '')[:60]
                break

        ts = msg.get('timestamp', '')
        bto_signals.append({
            'symbol': symbol,
            'trigger': trigger,
            'sl': sl_price,
            'ts': ts,
            'msg_id': msg.get('id', ''),
            'catalyst': catalyst,
            'title': title
        })

# Deduplicate: keep most recent per symbol (list is newest-first)
seen = set()
unique = []
for sig in bto_signals:
    if sig['symbol'] in seen:
        continue
    if sig['symbol'] == 'TT' and 'Test catalyst' in sig.get('catalyst', ''):
        print(f"SKIP test signal: {sig['symbol']} over ${sig['trigger']}")
        continue
    seen.add(sig['symbol'])
    unique.append(sig)

print(f"\n=== BTO Signals Found: {len(bto_signals)} total, {len(unique)} unique ===\n")
for i, sig in enumerate(unique, 1):
    sl_str = f"${sig['sl']}" if sig['sl'] else "N/A"
    print(f"{i}. {sig['symbol']} over ${sig['trigger']}  SL={sl_str}  [{sig['ts'][:19]}]")

# Now create conditional orders
print("\n=== Creating Conditional Orders ===\n")

from gui_app.database import create_conditional_order

CHANNEL_ID = '1509370338973319209'  # botifytrades-ai channel
BROKERS = ['SCHWAB', 'Webull']

created = 0
for sig in unique:
    for broker in BROKERS:
        sl_value = sig['sl']
        if not sl_value:
            sl_value = round(sig['trigger'] * 0.9, 4)  # Default 10% SL

        order_id = create_conditional_order(
            channel_id=CHANNEL_ID,
            symbol=sig['symbol'],
            trigger_type='over',
            trigger_price=sig['trigger'],
            broker_primary=broker,
            stop_loss_value=sl_value,
            size_mode='percent_account',
            qty_value=30.0,
            params_source='channel',
            original_message=sig['title'],
            asset_type='stock',
            message_id=sig['msg_id'],
            breakout_reset_enabled=1
        )
        if order_id:
            print(f"  Created #{order_id}: {sig['symbol']} over ${sig['trigger']} on {broker} (SL=${sl_value})")
            created += 1
        else:
            print(f"  FAILED: {sig['symbol']} on {broker}")

print(f"\n=== Done: {created} conditional orders created ===")
