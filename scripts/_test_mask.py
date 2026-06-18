import sys, os, io
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, '.')

from src.signals.temple_parser import (
    TEMPLE_ZZ_STRUCTURED_ENTRY, TEMPLE_ZZ_STRUCTURED_ENTRY_NO_TARGETS,
    parse_temple_zz_structured_entry
)
import re

# Exact signal as posted
sig = 'MASK \n✅ 2.60\n❌ 2.40\n\U0001f3af 2.73....2.84...2.90...3.00+'
print('Signal repr:', repr(sig))
print()

m = TEMPLE_ZZ_STRUCTURED_ENTRY.search(sig)
if m:
    print('MATCHED structured_entry')
    print('  symbol:', m.group(1))
    print('  entry:', m.group(2))
    print('  entry_low:', m.group(3))
    print('  sl:', m.group(4))
    print('  targets:', m.group(5))
    result = parse_temple_zz_structured_entry(m, sig)
    print('  Parsed:', {k: v for k, v in result.items() if v not in (None, [], False, '')})
else:
    print('NO MATCH on structured_entry')
    print()

    # Check each sub-pattern
    p1 = re.compile(r'^\$?([A-Z]{1,5})[ \t]*(?:<@&\d+>[ \t]*(?:/\w+)?[ \t]*)*[^\n]*\n', re.MULTILINE)
    p2 = re.compile(r'✅[ \t]*(?:around[ \t]+|(?:clear[ \t]+)?break[ \t]+(?:of[ \t]+)?)?(?:\$[ \t]*)?(\d+(?:\.\d+)?)[ \t]*(?:-[ \t]*(\d+(?:\.\d+)?))?[^\n]*\n')
    p3 = re.compile(r'(?:❌|➕)[ \t]*(?:(?:under|below)\s+)?(?:\$\s*)?-?(\d+(?:\.\d+)?)')
    p4 = re.compile(r'\U0001f3af[ \t]*([\d.,\s%+\-]+(?:\.{2,3}[\d.,\s%+\-]+)*)')

    m1 = p1.search(sig)
    m2 = p2.search(sig)
    m3 = p3.search(sig)
    m4 = p4.search(sig)
    print(f'  Line1 (symbol) matches: {bool(m1)} -> {m1.group(0)[:30] if m1 else None}')
    print(f'  Line2 (entry) matches:  {bool(m2)} -> {m2.group(0)[:30] if m2 else None}')
    print(f'  Line3 (sl) matches:     {bool(m3)} -> {m3.group(0)[:30] if m3 else None}')
    print(f'  Line4 (targets) matches:{bool(m4)} -> {m4.group(0)[:50] if m4 else None}')

    # Check if structured_entry_no_targets matches
    m_nt = TEMPLE_ZZ_STRUCTURED_ENTRY_NO_TARGETS.search(sig)
    print()
    print(f'  structured_entry_NO_TARGETS matches: {bool(m_nt)}')

    # Show the actual regex
    print()
    print('Structured entry pattern:')
    print(TEMPLE_ZZ_STRUCTURED_ENTRY.pattern)
