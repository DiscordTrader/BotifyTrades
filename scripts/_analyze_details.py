"""Detailed pattern analysis for specific traders."""
import json, re, sys, io, glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Find the file
import os
temp = os.environ.get('TEMP', r'C:\Users\risha\AppData\Local\Temp')
candidates = glob.glob(os.path.join(temp, 'extracted_*options*alerts*.json'))
if not candidates:
    print("No file found!")
    sys.exit(1)
filepath = candidates[0]
print(f"Using: {filepath}")

with open(filepath, 'r', encoding='utf-8') as f:
    data = json.load(f)

msgs = data['messages']

# Find Toughcookie standalone entries
tc_single = []
for m in msgs:
    c = m['content'].strip()
    if m['author_name'] == 'toughshit_' and not m.get('reply_to'):
        if re.search(r'[A-Z]{2,5}\s+\d+\s+[CP]', c, re.IGNORECASE) and len(c) < 80:
            tc_single.append(c)

print('=== Toughcookie standalone entries ===')
for c in tc_single:
    print(f'  "{c}"')

# Kizzy entries
kizzy = []
for m in msgs:
    c = m['content'].strip()
    if m['author_name'] == '_whynotyou' and not m.get('reply_to') and 10 < len(c) < 200:
        if re.search(r'\d+[cp]', c, re.IGNORECASE) and re.search(r'[A-Z]{2,5}', c):
            kizzy.append(c[:120])

print('\n=== Kizzy entries ===')
for c in kizzy:
    print(f'  "{c}"')

# ZZ spelled-out month
zz_spelled = []
for m in msgs:
    c = m['content'].strip()
    if m['author_name'] == 'traderzz1m' and re.search(r'(?:June|July|Aug|Sep|Jan|Feb|Mar|Apr|May|Oct|Nov|Dec)', c, re.IGNORECASE):
        if re.search(r'\d+\s*[cp]', c, re.IGNORECASE):
            zz_spelled.append(c[:120])

print('\n=== ZZ spelled-out month ===')
for c in zz_spelled:
    print(f'  "{c}"')

# Duke entries
duke = []
for m in msgs:
    c = m['content'].strip()
    if m['author_name'] == 'duke_nuchem' and re.search(r'\d+[cp]', c, re.IGNORECASE) and len(c) < 120:
        duke.append(c[:120])

print('\n=== Duke entries ===')
for c in duke:
    print(f'  "{c}"')

# TC back in
tc_backin = []
for m in msgs:
    c = m['content'].strip()
    if m['author_name'] == 'toughshit_' and re.search(r'back\s+in', c, re.IGNORECASE):
        tc_backin.append(c[:120])

print('\n=== TC back in ===')
for c in tc_backin:
    print(f'  "{c}"')

# Fawaz all messages
fawaz = []
for m in msgs:
    c = m['content'].strip()
    if m['author_name'] == 'sirfawazz' and len(c) > 10:
        fawaz.append(c[:140])

print('\n=== Fawaz all messages ===')
for c in fawaz:
    print(f'  "{c}"')

# ZZ role-first entries
zz_role = []
for m in msgs:
    c = m['content'].strip()
    if m['author_name'] == 'traderzz1m' and '<@&' in c and re.search(r'\$[A-Z]', c):
        zz_role.append(c[:140])

print('\n=== ZZ role-first entries ===')
for c in zz_role:
    print(f'  "{c}"')

# MSFT/META with "June/July DD" expiry
zz_month_day = []
for m in msgs:
    c = m['content'].strip()
    if m['author_name'] == 'traderzz1m':
        if re.search(r'[A-Z]{2,5}\s+\d+(?:\.\d+)?[cp]?\s+(?:June|July|Aug)\s+\d+', c, re.IGNORECASE):
            zz_month_day.append(c[:140])

print('\n=== ZZ MonthName Day entries ===')
for c in zz_month_day:
    print(f'  "{c}"')

# Count "PRICE C" updates from TC (current price updates)
tc_price_c = 0
for m in msgs:
    c = m['content'].strip()
    if m['author_name'] == 'toughshit_' and m.get('reply_to'):
        if re.match(r'^\d+(?:\.\d+)?\s*C\s*(?:\$.*)?$', c, re.IGNORECASE):
            tc_price_c += 1

print(f'\n=== TC "PRICE C" reply updates: {tc_price_c} ===')

# Dre "QQQ727c" (no space between ticker and strike)
dre_nospace = []
for m in msgs:
    c = m['content'].strip()
    if m['author_name'] == 'dre54501':
        if re.search(r'[A-Z]{2,5}\d+[cp]\s', c, re.IGNORECASE):
            dre_nospace.append(c[:100])

print('\n=== Dre no-space entries ===')
for c in dre_nospace:
    print(f'  "{c}"')

# Dre expiry in parens: "(06/12/26)"
dre_expiry = []
for m in msgs:
    c = m['content'].strip()
    if m['author_name'] == 'dre54501':
        if re.search(r'\(\d{2}/\d{2}/\d{2,4}\)', c):
            dre_expiry.append(c[:100])

print('\n=== Dre entries with expiry in parens ===')
for c in dre_expiry:
    print(f'  "{c}"')

# MrClean entries
mrclean = []
for m in msgs:
    c = m['content'].strip()
    if m['author_name'] == 'mrclean022224' and re.search(r'\d+[cp]', c, re.IGNORECASE):
        mrclean.append(c[:140])

print('\n=== MrClean entries ===')
for c in mrclean:
    print(f'  "{c}"')
