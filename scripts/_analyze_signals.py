"""Analyze Discord messages from options-alerts channel against temple parsers."""
import json, re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Load messages
with open(r'C:\Users\risha\AppData\Local\Temp\extracted_🚨│options-alerts💰_20260609_181248.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

msgs = data['messages']
print(f'Total messages: {len(msgs)}')

# Define all OPTIONS entry parsers (regex patterns from signal_format_registry)
ENTRY_PARSERS = {
    'temple_rf_options': re.compile(r'(?:\bbuy\s+)?\$?([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s*\+?\s*([CcPp])\s+at\s+\$?(\d+(?:\.\d+)?)\s+for\s+(\d{1,2}/\d{1,2}(?:/\d{2,4})?)', re.IGNORECASE),
    'temple_ts_options': re.compile(r'\$?([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s+(Puts?|Calls?)\s*[-–]?\s*(\.?\d+(?:\.\d+)?)\s+C\b', re.IGNORECASE),
    'temple_zz_options_a': re.compile(r'\$?([A-Z]{1,5})\s+([CcPp])\s+(\d+(?:\.\d+)?)\s+(daily|weekly|\d{1,2}/\d{1,2}(?:/\d{2,4})?)', re.IGNORECASE),
    'temple_zz_options_exp': re.compile(r'\$?([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s*([CcPp])\s+(\d{1,2})\.(\d{2})\s*exp\.?\s*(?:✅\s*)?(\.?\d+(?:\.\d+)?)', re.IGNORECASE),
    'temple_tc_options_range': re.compile(r'\$?([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s+([CcPp])\s*[-–]?\s*(\.?\d+(?:\.\d+)?)\s*[-–]\s*\.?\d+(?:\.\d+)?\s*C?\b', re.IGNORECASE),
    'temple_zz_options_b': re.compile(r'\$?([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s*([CcPp])\s+(\d+(?:\.\d+)?)(?!\s*/)(?!\d)', re.IGNORECASE),
    'temple_options_standard': re.compile(r'\$?([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s*([CcPp])\s+@\s*\$?(\.?\d+(?:\.\d+)?)', re.IGNORECASE),
}

# Exit parser
EXIT_PARSER = re.compile(r'\b(?:out|sold|cut|SL\s+out)\s+\$?([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s*([CcPp])', re.IGNORECASE)

# Exit word patterns
EXIT_PRICE = re.compile(r'^(?:Out|Half\s+out|More\s+out|Sold\s+(?:some|half|most)?|1/[234]\s+out|3/4\s+out)\s+(?:@?\s*\$?)(\d+(?:\.\d+)?)', re.IGNORECASE)
EXIT_BE = re.compile(r'\bout\s+BE\b', re.IGNORECASE)
EXIT_CUT = re.compile(r'^Cut(?:\s|\.|\s+\d|$)', re.IGNORECASE)
EXIT_SL_OUT = re.compile(r'^SL\s+out\b', re.IGNORECASE)
EXIT_STOPPED = re.compile(r'^Stopped\b', re.IGNORECASE)
EXIT_CUTTING = re.compile(r'^(?:Cutting|out completely|out here\b|out no\b)', re.IGNORECASE)

# Known trader IDs
TRADERS = {
    'traderzz1m': 'ZZ',
    'rf0496_76497': 'RF',
    'legacytrading506': 'Legacy Trading',
    'toughshit_': 'Toughcookie',
    'dre54501': 'Dre5450',
    '_whynotyou': 'Kizzy',
    'duke_nuchem': 'Duke Nuchem',
    'sirfawazz': 'Fawaz',
}

entries = []
exits = []
updates = []
commentary = []

for m in msgs:
    content = m['content'].strip()
    author = m['author_display']
    author_name = m['author_name']

    if not content:
        commentary.append(m)
        continue

    # Check entry parsers first
    matched_entry = None
    for name, pat in ENTRY_PARSERS.items():
        match = pat.search(content)
        if match:
            # Filter false positives
            if name == 'temple_zz_options_b':
                # Skip if starts with BTO/STC/BUY/SELL
                if re.match(r'^\s*(?:BTO|STC|BUY|SELL)\s', content, re.IGNORECASE):
                    continue
                # Skip if has DD.MM exp pattern
                if re.search(r'\d{2}\.\d{2}\s*exp', content, re.IGNORECASE):
                    continue
            matched_entry = name
            break

    # Check exit parser
    matched_exit = EXIT_PARSER.search(content)

    # Classify
    if matched_entry:
        entries.append({'parser': matched_entry, 'content': content, 'author': author, 'author_name': author_name, 'reply_to': m.get('reply_to')})
    elif matched_exit:
        exits.append({'parser': 'temple_options_exit', 'content': content, 'author': author, 'author_name': author_name})
    elif EXIT_PRICE.search(content) or EXIT_BE.search(content) or EXIT_CUT.match(content) or EXIT_SL_OUT.match(content) or EXIT_STOPPED.match(content):
        exits.append({'parser': None, 'content': content, 'author': author, 'author_name': author_name})
    elif EXIT_CUTTING.search(content) and len(content) < 80:
        exits.append({'parser': None, 'content': content, 'author': author, 'author_name': author_name})
    else:
        # Check update patterns
        is_update = False
        # Price range reply (e.g., ".65-2.00", "0.95-10.67")
        if re.match(r'^\.?\d+(?:\.\d+)?\s*[-–]\s*\.?\d+(?:\.\d+)?(?:\s|$)', content) and m.get('reply_to'):
            is_update = True
        # SL update standalone
        elif re.match(r'^SL\s+\.?\d+', content, re.IGNORECASE) and len(content) < 15:
            is_update = True
        # Target done
        elif re.search(r'(?:target|PT)\s+done|all\s+targets', content, re.IGNORECASE):
            is_update = True
        # Move stops
        elif re.search(r'(?:move\s+(?:your\s+)?(?:stop|SL|sl)|stops?\s+(?:at|to))', content, re.IGNORECASE):
            is_update = True
        # Percentage update
        elif re.match(r'^\+?\d+%\s', content):
            is_update = True
        # Price update with "now"/"hit"/"so far"/"tapped"
        elif re.search(r'(?:\d+(?:\.\d+)?\s+(?:now|hit|tapped|so far))|(?:(?:hit|tapped)\s+\d)', content, re.IGNORECASE) and len(content) < 50:
            is_update = True
        # Price update as reply (just a number)
        elif re.match(r'^\d+(?:\.\d+)?$', content) and m.get('reply_to'):
            is_update = True
        # Price with C as reply (Toughcookie's current price updates)
        elif re.match(r'^\d+(?:\.\d+)?\s*C\s*$', content, re.IGNORECASE) and m.get('reply_to'):
            is_update = True
        # X% move stops
        elif re.search(r'\d+%\s+move\s+stop', content, re.IGNORECASE):
            is_update = True
        # "back in" re-entry (update to existing position)
        elif re.match(r'^back\s+in\s+\d', content, re.IGNORECASE) and m.get('reply_to'):
            is_update = True
        # "added" average
        elif re.match(r'^(?:added|again\s+at)\s+', content, re.IGNORECASE) and m.get('reply_to'):
            is_update = True
        # ".XX-.YY please move stops"
        elif re.match(r'^\.?\d+(?:\.\d+)?\s*[-–]\s*\.?\d+', content) and m.get('reply_to'):
            is_update = True
        # SL at BE
        elif re.search(r'SL\s+(?:at\s+)?BE\b', content, re.IGNORECASE):
            is_update = True
        # Recap
        elif re.search(r'Options\s+Alert.*Recap', content, re.IGNORECASE):
            is_update = True
        # Watch list
        elif re.search(r'Watch\s+List', content, re.IGNORECASE):
            is_update = True
        # Futures data
        elif re.search(r'E-mini\s+futures', content, re.IGNORECASE):
            is_update = True

        if is_update:
            updates.append(m)
        else:
            commentary.append(m)

print(f'\nEntries: {len(entries)}')
print(f'Exits: {len(exits)}')
print(f'Updates: {len(updates)}')
print(f'Commentary: {len(commentary)}')

# ========== ENTRY ANALYSIS ==========
print('\n' + '='*80)
print('ENTRY SIGNALS BY PARSER')
print('='*80)

parser_counts = {}
for e in entries:
    p = e['parser']
    if p not in parser_counts:
        parser_counts[p] = []
    parser_counts[p].append(e)

for p, items in sorted(parser_counts.items(), key=lambda x: -len(x[1])):
    print(f'\n--- {p} ({len(items)} signals) ---')
    # Group by author
    by_author = {}
    for item in items:
        a = item['author']
        if a not in by_author:
            by_author[a] = []
        by_author[a].append(item)
    for a, aitems in by_author.items():
        print(f'  [{a}] ({len(aitems)} signals)')
        for item in aitems[:3]:
            print(f'    "{item["content"][:100]}"')

# ========== EXIT ANALYSIS ==========
print('\n' + '='*80)
print('EXIT SIGNALS')
print('='*80)

recognized_exits = [e for e in exits if e['parser']]
unrecognized_exits = [e for e in exits if not e['parser']]

print(f'\nRecognized by temple_options_exit: {len(recognized_exits)}')
for e in recognized_exits:
    print(f'  [{e["author"]}] "{e["content"][:80]}"')

print(f'\nUnrecognized exits (no parser): {len(unrecognized_exits)}')

# Group unrecognized exits by pattern
exit_patterns = {}
for e in unrecognized_exits:
    c = e['content']
    if EXIT_PRICE.search(c):
        pat = 'Out/Half out/Sold PRICE'
    elif EXIT_BE.search(c):
        pat = 'Out BE'
    elif EXIT_CUT.match(c):
        pat = 'Cut [PRICE]'
    elif EXIT_SL_OUT.match(c):
        pat = 'SL out'
    elif EXIT_STOPPED.match(c):
        pat = 'Stopped'
    elif EXIT_CUTTING.search(c):
        pat = 'Cutting/out completely/out here'
    else:
        pat = 'OTHER'
    if pat not in exit_patterns:
        exit_patterns[pat] = []
    exit_patterns[pat].append(e)

for pat, items in sorted(exit_patterns.items(), key=lambda x: -len(x[1])):
    print(f'\n  Pattern: "{pat}" ({len(items)} exits)')
    for item in items[:5]:
        print(f'    [{item["author"]}] "{item["content"][:80]}"')
    if len(items) > 5:
        print(f'    ... and {len(items)-5} more')

# ========== FIND MISSING ENTRIES ==========
print('\n' + '='*80)
print('POTENTIAL MISSING ENTRY SIGNALS (in commentary)')
print('='*80)

# Search commentary for things that look like entries but weren't caught
missing_entries = []
for m in commentary:
    content = m['content'].strip()
    author_name = m['author_name']
    author = m['author_display']

    if not content or len(content) > 200:
        continue

    # Dre: "TICKER STRIKEc/p @ PRICE (stuff)" with no space before c/p
    if re.search(r'[A-Z]{2,5}\d+[cp]\s*@\s*\.?\d', content, re.IGNORECASE):
        missing_entries.append({'content': content, 'author': author, 'author_name': author_name, 'pattern': 'TICKER+STRIKEc @ PRICE (no space)'})
        continue

    # ZZ: "$TICKER $STRIKE C MONTH DAY PRICE" (spelled out expiry)
    if re.search(r'\$?[A-Z]{2,5}\s+\d+(?:\.\d+)?\s+[cp]\s+(?:June|July|Aug|Sep|Jan|Feb|Mar|Apr|May|Oct|Nov|Dec)\s+\d+', content, re.IGNORECASE):
        missing_entries.append({'content': content, 'author': author, 'author_name': author_name, 'pattern': 'TICKER STRIKE C MonthName Day PRICE'})
        continue

    # ZZ: "SPY c 755 will load" or "SPY c 755 PRICE daily"
    if re.search(r'[A-Z]{2,5}\s+[cp]\s+\d+\s+(?:\d+(?:\.\d+)?\s+)?(?:will|daily|weekly)', content, re.IGNORECASE):
        missing_entries.append({'content': content, 'author': author, 'author_name': author_name, 'pattern': 'TICKER C/P STRIKE intent/daily'})
        continue

    # Kizzy multiline: "TICKER MM/DD STRIKEc PRICE"
    if re.search(r'[A-Z]{2,5}\s+\d{2}/\d{2}\s+\d+[cp]', content, re.IGNORECASE):
        missing_entries.append({'content': content, 'author': author, 'author_name': author_name, 'pattern': 'TICKER MM/DD STRIKEc PRICE'})
        continue

    # Kizzy: "Ticker STRIKEc MM/DD PRICE <@&role>"
    if re.search(r'[A-Z]{2,5}\s+\d+[cp]\s+\d{2}/\d{2}\s+\d', content, re.IGNORECASE):
        missing_entries.append({'content': content, 'author': author, 'author_name': author_name, 'pattern': 'TICKER STRIKEc MM/DD PRICE'})
        continue

    # Duke: "TICKER STRIKEc" with no price
    if re.search(r'^[A-Z]{2,5}\s+\d+[cp]\s*$', content, re.IGNORECASE) and author_name == 'duke_nuchem':
        missing_entries.append({'content': content, 'author': author, 'author_name': author_name, 'pattern': 'TICKER STRIKEc (no price)'})
        continue

    # Fawaz: "BAC C57.50 17/7 my Ask 0.80"
    if re.search(r'[A-Z]{2,5}\s+[CP]\d+', content, re.IGNORECASE):
        missing_entries.append({'content': content, 'author': author, 'author_name': author_name, 'pattern': 'TICKER C+STRIKE (Fawaz style)'})
        continue

    # Duke: "TICKER STRIKEc MM/DD <@&role>"
    if re.search(r'[A-Z]{2,5}\s+\d+[cp]\s+\d{1,2}/\d{1,2}', content, re.IGNORECASE):
        missing_entries.append({'content': content, 'author': author, 'author_name': author_name, 'pattern': 'TICKER STRIKEc MM/DD (Duke style)'})
        continue

    # ZZ role: "<@&role> $TICKER $STRIKEc EXPIRY PRICE"
    if re.search(r'<@&\d+>\s*\$?[A-Z]{2,5}\s+\$?\d+', content):
        missing_entries.append({'content': content, 'author': author, 'author_name': author_name, 'pattern': 'Role $TICKER $STRIKE (ZZ role-first)'})
        continue

    # Kizzy structured: "Lotto <@&role>\nTICKER MM/DD STRIKEc"
    if re.search(r'(?:Lotto|Entry|Starting)', content, re.IGNORECASE) and re.search(r'[A-Z]{2,5}.*\d+[cp]', content, re.IGNORECASE):
        if author_name in ('_whynotyou', 'duke_nuchem', 'sirfawazz'):
            missing_entries.append({'content': content[:100], 'author': author, 'author_name': author_name, 'pattern': 'Structured multi-line entry'})
            continue

    # "Consider TICKER for EXPIRY STRIKE C"
    if re.search(r'Consider\s+[A-Z]{2,5}', content, re.IGNORECASE):
        missing_entries.append({'content': content, 'author': author, 'author_name': author_name, 'pattern': 'Consider TICKER (suggestion)'})
        continue

    # TC: "QQQ STRIKE P/C PRICE" with no dash range (single price)
    if re.search(r'^[A-Z]{2,5}\s+\d+\s+[CP]\s+\d+(?:\.\d+)?\s*$', content, re.IGNORECASE):
        missing_entries.append({'content': content, 'author': author, 'author_name': author_name, 'pattern': 'TICKER STRIKE C/P PRICE (single, no SL)'})
        continue

    # TC: "QQQ STRIKE P .PRICE C SL" (cost style with 'C' for cost)
    if re.search(r'[A-Z]{2,5}\s+\d+\s+[CP]\s+\.?\d+(?:\.\d+)?\s+C\s+SL', content, re.IGNORECASE):
        missing_entries.append({'content': content, 'author': author, 'author_name': author_name, 'pattern': 'TICKER STRIKE P PRICE C SL (TC single price)'})
        continue

    # Toughcookie re-entry: "back in PRICE C" as reply
    if re.match(r'^back\s+in\s+\d+(?:\.\d+)?\s+C', content, re.IGNORECASE) and m.get('reply_to'):
        missing_entries.append({'content': content, 'author': author, 'author_name': author_name, 'pattern': 'back in PRICE C (re-entry)'})
        continue

    # "PRICE c back in" as reply
    if re.match(r'^\d+(?:\.\d+)?\s+c\s+back\s+in', content, re.IGNORECASE) and m.get('reply_to'):
        missing_entries.append({'content': content, 'author': author, 'author_name': author_name, 'pattern': 'PRICE C back in (re-entry)'})
        continue

print(f'\nFound {len(missing_entries)} potentially missing entry signals:')
pat_groups = {}
for me in missing_entries:
    p = me['pattern']
    if p not in pat_groups:
        pat_groups[p] = []
    pat_groups[p].append(me)

for p, items in sorted(pat_groups.items(), key=lambda x: -len(x[1])):
    print(f'\n  Pattern: "{p}" ({len(items)} signals)')
    for item in items[:5]:
        print(f'    [{item["author"]}] "{item["content"][:100]}"')
    if len(items) > 5:
        print(f'    ... and {len(items)-5} more')

# ========== SUMMARY ==========
print('\n' + '='*80)
print('SUMMARY')
print('='*80)
recognized_entries = [e for e in entries if e['parser'] != 'UNRECOGNIZED']
unrecognized_entries = [e for e in entries if e['parser'] == 'UNRECOGNIZED']
total_signals = len(recognized_entries) + len(recognized_exits)
total_missing = len(unrecognized_entries) + len(unrecognized_exits) + len(missing_entries)
print(f'Recognized entry signals: {len(recognized_entries)}')
print(f'Recognized exit signals: {len(recognized_exits)}')
print(f'Unrecognized entry signals: {len(unrecognized_entries)}')
print(f'Unrecognized exit signals: {len(unrecognized_exits)}')
print(f'Missing entries in commentary: {len(missing_entries)}')
print(f'Total recognized: {total_signals}')
print(f'Total missing: {total_missing}')
print(f'Updates: {len(updates)}')
print(f'Commentary: {len(commentary)}')
