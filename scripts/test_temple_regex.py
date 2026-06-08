"""Test TEMPLE_ZZ_RANGE_ENTRY regex against all TEMP-BOOM channel messages."""
import sys, os
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
from src.signals.temple_parser import TEMPLE_ZZ_RANGE_ENTRY, TEMPLE_ZZ_STRUCTURED_ENTRY, TEMPLE_ZZ_BREAKOUT

messages = [
    ('SLXN 0.62-0.72. 0.72 must break for 0.78...0.88', 'Commentary w/ trailing'),
    ('PHGE 0.55-0.64 so far', 'Commentary w/ "so far"'),
    ('GCL 0.77-0.95 so far.  1.09 above', 'Commentary w/ "so far"'),
    ('SUGP 4.50-6.31 <a:4743_pink_flame:1154098186831536248>', 'Range + flame'),
    ('CAPS 0.35-0.43<a:4743_pink_flame:1154098186831536248>', 'Range + flame (no space)'),
    ('NXXT 0.75-0.88<a:4743_pink_flame:1154098186831536248>', 'Range + flame'),
    ('HCWB 0.99-1.76.... all fibs hit', 'Range + trailing text'),
    ('MTVA all PTs hit 2.07-2.73<a:4743_pink_flame:1154098186831536248>', 'Prefix text before range'),
    ('CODX 2.05-2.43<a:4743_pink_flame:1154098186831536248>', 'Range + flame'),
    ('PHGE 0.55-0.67<a:4743_pink_flame:1154098186831536248>', 'Range + flame'),
    ('MTVA 2.70-2.96<a:4743_pink_flame:1154098186831536248>', 'Range + flame'),
    ('VIDA 2.86-3.64<a:4743_pink_flame:1154098186831536248>', 'Range + flame'),
    ('WNW 4.00-6.54. Over 7.25 we have 8.39 <a:4743_pink_flame:1154098186831536248>', 'Range + trailing'),
    # Structured format
    ('If you missed my 2.07 alert on MTVA. Consider \n✅ 2.70\n❌ 2.50\n🎯 5% 10% 15%', 'ZZ structured emoji'),
    # Overnight trade
    ('Overnight trade idea 🌙 \n$MTVA re-entry\n✅ 2.60-2.65\n❌ 2.50\n🎯 2.75...3.00...3.12..3.30..3.60', 'ZZ structured overnight'),
]

print("=" * 120)
print(f"{'STATUS':10} | {'NOTE':45} | MESSAGE")
print("=" * 120)

for msg, note in messages:
    m_range = TEMPLE_ZZ_RANGE_ENTRY.match(msg)
    m_struct = TEMPLE_ZZ_STRUCTURED_ENTRY.search(msg)
    m_break = TEMPLE_ZZ_BREAKOUT.search(msg)

    if m_range:
        groups = m_range.groups()
        print(f"{'RANGE':10} | {note:45} | {msg[:70]}")
        print(f"{'':10} | -> sym={groups[0]}, entry={groups[1]}, target={groups[2]}")
    elif m_struct:
        groups = m_struct.groups()
        print(f"{'STRUCTURED':10} | {note:45} | {msg[:70]}")
        print(f"{'':10} | -> sym={groups[0]}, entry={groups[1]}, sl={groups[3]}, targets={groups[4]}")
    elif m_break:
        groups = m_break.groups()
        print(f"{'BREAKOUT':10} | {note:45} | {msg[:70]}")
        print(f"{'':10} | -> groups={groups}")
    else:
        print(f"{'NO MATCH':10} | {note:45} | {msg[:70]}")
