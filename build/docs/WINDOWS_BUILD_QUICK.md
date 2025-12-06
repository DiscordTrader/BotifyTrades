# Ψ∿ QuantumPulse - Windows Build (Quick Guide)

**Date:** 2025-11-21  
**For:** Windows 10/11 (64-bit)

---

## ⚡ COPY & PASTE COMMANDS

### Step 1: Open Command Prompt or PowerShell
```
Win + R
cmd
Enter
```

### Step 2: Navigate to Your Project
```
cd C:\Replitbot\GUI\DiscordWebullBotv11\DiscordWebullBot
```
*(Replace with YOUR actual path)*

### Step 3: Clean Previous Build (if exists)
```
rmdir /s /q dist build
```

### Step 4: Install Dependencies (one-time)
```
pip install --upgrade pip setuptools wheel
pip install pyinstaller
pip install -r requirements.txt
```

### Step 5: Build the EXE
```
pyinstaller build_windows.spec
```

**Wait 5-15 minutes for build to complete...**

### Step 6: Find Your EXE
Look for folder:
```
dist\QuantumPulse_Windows_Build_2025-11-21\QuantumPulse.exe
```

### Step 7: Test Run
```
cd dist\QuantumPulse_Windows_Build_2025-11-21
QuantumPulse.exe
```

---

## ✅ What to Expect

**Console Output:**
```
[Init] Script starting - clean logging enabled
[Discord] ✓ Monitoring channels
[GUI] ✓ Web control panel started on port 5000
```

**Then open browser:**
```
http://localhost:5000
```

---

## ⚠️ If It Fails

### Error: "pyinstaller: command not found"
```
pip install pyinstaller
```

### Error: "Module not found"
```
pip install -r requirements.txt
```

### Error: "Python not found"
Reinstall Python 3.11 with "Add to PATH" checked

### Error: "strip command not found"
Already fixed in `build_windows.spec` - use the latest file

---

## 🎯 Success = 3 Things:
1. ✓ `.exe` file created (~200MB)
2. ✓ Runs without errors
3. ✓ Web GUI loads at localhost:5000

---

**Build Date:** 2025-11-21
**Status:** Ready to build ✅
