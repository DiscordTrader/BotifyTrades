"""Temporary script to check unmatched signals."""
import json, sys, re
sys.path.insert(0, "src")

from signals.temple_parser import (
    parse_temple_zz_structured_entry,
    parse_temple_zz_structured_entry_no_targets,
    parse_temple_zz_single_line_entry,
    parse_temple_zz_plain_entry,
    parse_temple_zz_inline_role_entry,
)

# All structured entry patterns from signal_format_registry.py
PATTERNS = [
    (r'([A-Z]{1,5})\s*\n\s*✅\s*\$?(\d+(?:\.\d+)?)\s*(?:[-–]\s*\$?(\d+(?:\.\d+)?))?\s*\n\s*❌\s*\$?(\d+(?:\.\d+)?)\s*\n\s*🎯\s*(.*?)$',
     parse_temple_zz_structured_entry, "structured_entry"),
    (r'([A-Z]{1,5})\s*\n\s*✅\s*\$?(\d+(?:\.\d+)?)\s*(?:[-–]\s*\$?(\d+(?:\.\d+)?))?\s*\n\s*❌\s*\$?(\d+(?:\.\d+)?)\s*$',
     parse_temple_zz_structured_entry_no_targets, "structured_no_targets"),
    (r'([A-Z]{1,5})\s+✅\s*\$?(\d+(?:\.\d+)?)\s*(?:[-–]\s*\$?(\d+(?:\.\d+)?))?\s+❌\s*\$?(\d+(?:\.\d+)?)\s+🎯\s*(.*?)$',
     parse_temple_zz_single_line_entry, "single_line"),
    (r'([A-Z]{1,5})\s+\$?(\d+(?:\.\d+)?)\s*(?:[-–]\s*\$?(\d+(?:\.\d+)?))?\s*$',
     parse_temple_zz_plain_entry, "plain_entry"),
    (r'<@&\d+>\s+([A-Z]{1,5})\s+✅\s*\$?(\d+(?:\.\d+)?)\s*(?:[-–]\s*\$?(\d+(?:\.\d+)?))?\s+❌\s*\$?(\d+(?:\.\d+)?)\s+🎯\s*(.*?)$',
     parse_temple_zz_inline_role_entry, "inline_role"),
]

with open(r"C:\Users\risha\AppData\Local\Temp\extracted_⚡│zz_20260609_081426.json", "r", encoding="utf-8") as f:
    data = json.load(f)
    msgs = data.get("messages", data) if isinstance(data, dict) else data

unmatched = []
matched = 0
for i, m in enumerate(msgs):
    content = m.get("content", "")
    if "✅" not in content:  # ✅
        continue

    found = False
    for pat, parser, name in PATTERNS:
        match = re.search(pat, content, re.DOTALL | re.MULTILINE)
        if match:
            result = parser(match, content)
            if result and result.get("ticker"):
                matched += 1
                found = True
                break

    if not found:
        unmatched.append((i, content[:300]))

print(f"Matched: {matched}, Unmatched: {len(unmatched)}")
for idx, (i, c) in enumerate(unmatched):
    print(f"\n--- #{i} ---")
    print(repr(c).encode('ascii', 'replace').decode())
