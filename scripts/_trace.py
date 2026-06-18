with open('src/selfbot_webull.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

indent_17155 = len(lines[17154]) - len(lines[17154].lstrip())
print(f"Line 17155 indent: {indent_17155}")

for i in range(17154, 14000, -1):
    line = lines[i]
    stripped = line.lstrip()
    spaces = len(line) - len(line.lstrip())
    if spaces < indent_17155 and (stripped.startswith('if ') or stripped.startswith('else') or stripped.startswith('elif ')):
        print(f"Line {i+1}: indent={spaces} | {line.rstrip()[:120]}")
        if spaces <= 8:
            break
