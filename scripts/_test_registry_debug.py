import sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.signal_format_registry import get_signal_format_registry
registry = get_signal_format_registry()

# Debug temple_zz_ticker_price_now
text = "$EZGO 3.28 now"
clean = registry._strip_discord_mentions(text.strip())
print(f"raw: '{text}' -> clean: '{clean}'")

# Try matching directly
for fmt in registry._sorted_formats:
    if fmt.name == "temple_zz_ticker_price_now":
        match_text = clean  # not in role-aware
        m = fmt.pattern.search(match_text)
        print(f"Direct match: {m}")
        print(f"Pattern: {fmt.pattern.pattern}")
        print(f"Flags: {fmt.pattern.flags}")
        if m:
            result = fmt.parser(m, match_text)
            print(f"Parser result: {result}")
        break

# Check what format catches it first
print(f"\nregistry.parse('{text}'): {registry.parse(text)}")

# Debug viking_entry_role_first
text2 = "<@&1330929339134640179> $Anpa 6.5$"
print(f"\nViking test raw: '{text2}'")
clean2 = registry._strip_discord_mentions(text2.strip())
print(f"Viking clean: '{clean2}'")

for fmt in registry._sorted_formats:
    if fmt.name == "viking_entry_role_first":
        # viking is not in role-aware formats so it uses clean_text
        # but clean_text strips the <@&...> which the pattern needs!
        is_role_aware = fmt.name in registry._ROLE_AWARE_FORMATS
        match_text = text2.strip() if is_role_aware else clean2
        print(f"Role aware: {is_role_aware}")
        print(f"Match text: '{match_text}'")
        m = fmt.pattern.search(match_text)
        print(f"Match: {m}")
        break

# Debug single_line_entry
text3 = "CTNT <@&momentum> <@&swing> 2.18"
clean3 = registry._strip_discord_mentions(text3.strip())
print(f"\nSingle-line raw: '{text3}'")
print(f"Single-line clean: '{clean3}'")
for fmt in registry._sorted_formats:
    if fmt.name == "temple_zz_single_line_entry":
        is_role_aware = fmt.name in registry._ROLE_AWARE_FORMATS
        match_text = text3.strip() if is_role_aware else clean3
        print(f"Role aware: {is_role_aware}")
        print(f"Match text: '{match_text}'")
        m = fmt.pattern.search(match_text)
        print(f"Match: {m}")
        break
