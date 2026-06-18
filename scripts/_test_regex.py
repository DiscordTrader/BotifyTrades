import re

# Test temple_zz_ticker_price_now
pat = re.compile(r'^\$?([A-Z]{2,5})\s+(\d+(?:\.\d+)?)\s+now$', re.IGNORECASE)
tests = ["$EZGO 3.28 now", "ERNA 5.50 now", "$EZGO 3.28 now\n"]
for t in tests:
    m = pat.search(t)
    print(f"  '{t.strip()}' -> {m}")

# The issue: registry compiles patterns and uses .search() on the full message text
# which may have trailing newlines or whitespace. The $ anchor blocks that.
# Fix: use \s*$ instead of $ to handle trailing whitespace

pat2 = re.compile(r'^\$?([A-Z]{2,5})\s+(\d+(?:\.\d+)?)\s+now\s*$', re.IGNORECASE)
for t in tests:
    m = pat2.search(t)
    print(f"  fixed '{t.strip()}' -> {m}")

# Test temple_zz_ciss_reversal
# Pattern: r'^\$?([A-Z]{2,5})\s+for\s+the\s+reversal\s+(?:here\s+)?(?:at\s+)?\$?(\d+(?:\.\d+)?)'
# Example: "ASBP 0.32 for the reversal" - price BEFORE "for the reversal"
pat3 = re.compile(r'^\$?([A-Z]{2,5})\s+for\s+the\s+reversal\s+(?:here\s+)?(?:at\s+)?\$?(\d+(?:\.\d+)?)', re.IGNORECASE)
print(f"\nciss_reversal current: 'ASBP 0.32 for the reversal' -> {pat3.search('ASBP 0.32 for the reversal')}")
print(f"ciss_reversal current: '$CISS for the reversal here at 2.55' -> {pat3.search('$CISS for the reversal here at 2.55')}")

# Fix: also allow SYMBOL PRICE for the reversal
pat4 = re.compile(r'^\$?([A-Z]{2,5})\s+(?:for\s+the\s+reversal\s+(?:here\s+)?(?:at\s+)?\$?(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s+for\s+the\s+reversal)', re.IGNORECASE)
print(f"ciss_reversal fixed: 'ASBP 0.32 for the reversal' -> {pat4.search('ASBP 0.32 for the reversal')}")
print(f"ciss_reversal fixed: '$CISS for the reversal here at 2.55' -> {pat4.search('$CISS for the reversal here at 2.55')}")

# Test viking_entry_role_first
# Pattern: r'<@&\d+>\s+(?:.*?\s+)?\$([A-Za-z]{1,5})\s+\$?(\.?\d+(?:\.\d+)?)\$?'
pat5 = re.compile(r'<@&\d+>\s+(?:.*?\s+)?\$([A-Za-z]{1,5})\s+\$?(\.?\d+(?:\.\d+)?)\$?', re.IGNORECASE)
tests5 = [
    "<@&1330929339134640179> $Anpa 6.5$",
    "<@&1330929339134640179> $Dxf .4450",
    "<@&1330915546513805463> $Anpa 6.50 short term swing",
]
print("\nviking_entry_role_first:")
for t in tests5:
    m = pat5.search(t)
    print(f"  '{t}' -> {m}")
    if m:
        print(f"    groups: {m.groups()}")

# Test temple_zz_will_enter_if_breaks
pat6 = re.compile(r'^\$?([A-Z]{1,5})\s+(?:I\s+)?will\s+(?:only\s+)?(?:re-?)?enter\s+(?:only\s+)?(?:if\s+)?(?:it\s+)?(?:give[s]?\s+(?:us\s+)?(?:a\s+)?)?(?:clear\s+)?(?:strong\s+)?(?:bre?a?k(?:s)?(?:\s+(?:and\s+)?holds?)?\s+(?:of\s+)?|(?:at\s+(?:a\s+)?)?(?:clear\s+)?)\$?(\d+(?:\.\d+)?)\s+(?:for|(?:bre?a?k\s+)?for)\s+(.+)', re.IGNORECASE)
tests6 = [
    "$MIMI will enter at a $4.00 clear break for 4.25-4.70-5.20",
    "$DRTS good news - will enter a strong 10.19 break for 11.10-11.97",
]
print("\nwill_enter_if_breaks:")
for t in tests6:
    m = pat6.search(t)
    print(f"  '{t}' -> {m}")

# Test temple_zz_i_will_take_break
pat7 = re.compile(r'^\$?([A-Z]{1,5})\s+I\s+will\s+(?:take|buy)\s+(?:(?:clear\s+)?bre?a?k\s+(?:of\s+)?)?\$?(\d+(?:\.\d+)?)\s*(?:bre?a?k)?(?:\s+for\s+(.+))?', re.IGNORECASE)
print(f"\ni_will_take_break: '$DARE I will buy if it breaks 2.80 for 3.00+' -> {pat7.search('$DARE I will buy if it breaks 2.80 for 3.00+')}")

# Test temple_zz_single_line_entry
pat8 = re.compile(r'^\$?([A-Z]{1,5})\s*(?:<@&\d+>\s*)+(?:✅\s*)?(?:\$\s*)?(\d+(?:\.\d+)?)(?:\s*-\s*(\d+(?:\.\d+)?))?', re.IGNORECASE)
tests8 = [
    "$ACXP <@&swing> ✅ 1.75-1.80",
    "CTNT <@&momentum> <@&swing> 2.18",
]
print("\nsingle_line_entry:")
for t in tests8:
    m = pat8.search(t)
    print(f"  '{t}' -> {m}")
    if m:
        print(f"    groups: {m.groups()}")
