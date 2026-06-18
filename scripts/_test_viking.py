import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["PYTHONIOENCODING"] = "utf-8"

from src.services.signal_format_registry import SignalFormatRegistry
registry = SignalFormatRegistry()

with open('extracted_⚔│viking-plays_20260606_212144.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

entries = []
exits = []
skipped = []
false_positives = []

for m in data['messages']:
    content = m['content'].strip()
    if not content or len(content) < 3:
        continue

    results = registry.parse_all(content)
    viking_results = [r for r in results if r.get('_format_name', '').startswith('viking_')]

    if viking_results:
        r = viking_results[0]
        fmt = r.get('_format_name')
        if r.get('action') == 'BTO':
            entries.append((content[:80], fmt, r.get('symbol'), r.get('price'), r.get('stop_loss'), r.get('_viking_trade_type')))
        elif r.get('action') == 'STC':
            exits.append((content[:80], fmt, r.get('symbol')))
    else:
        # Check if this LOOKS like a signal we missed
        if '$' in content and any(c.isdigit() for c in content):
            has_role = '<@&' in content
            has_kw = any(kw in content.lower() for kw in ['loto', 'starter', 'took', 'entry', 'added', 'adding', 'joined'])
            if has_role or has_kw:
                skipped.append(content[:100])

print(f"=== ENTRIES ({len(entries)}) ===")
for msg, fmt, sym, price, sl, tt in entries:
    sl_str = f" SL=${sl}" if sl else ""
    print(f"  {fmt}: {sym} @ ${price} [{tt}]{sl_str} | {msg}")

print(f"\n=== EXITS ({len(exits)}) ===")
for msg, fmt, sym in exits:
    print(f"  {fmt}: {sym} | {msg}")

print(f"\n=== POTENTIALLY MISSED ({len(skipped)}) ===")
for msg in skipped[:20]:
    print(f"  ? {msg}")

print(f"\n=== SUMMARY ===")
print(f"  Entries: {len(entries)}")
print(f"  Exits: {len(exits)}")
print(f"  Potentially missed: {len(skipped)}")
print(f"  Total messages: {len(data['messages'])}")
