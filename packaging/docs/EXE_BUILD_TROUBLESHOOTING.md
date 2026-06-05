# EXE Build Troubleshooting Guide

## ❌ Problem: `build_exe.bat` flashes and closes immediately

### Solution: Run from Command Prompt to see the error

Instead of double-clicking the batch file, open it in Command Prompt:

1. **Open Command Prompt**:
   - Press `Win + R`
   - Type `cmd` and press Enter

2. **Navigate to your project folder**:
   ```cmd
   cd C:\path\to\EXE_Distribution
   ```

3. **Run the batch file**:
   ```cmd
   build_exe.bat
   ```

Now you'll see the actual error message and the window will stay open!

---

## Common Errors & Solutions

### ❌ Error: "Python is not installed or not in PATH!"

**Cause**: Python is not installed or not added to Windows PATH

**Solution**:
1. Download Python 3.11+ from [python.org](https://www.python.org/downloads/)
2. During installation, **CHECK** ✅ "Add Python to PATH"
3. Restart Command Prompt
4. Test: `python --version`

---

### ❌ Error: "pip install failed" or "access denied"

**Cause**: Insufficient permissions or pip needs updating

**Solution**:
1. Run Command Prompt **as Administrator**:
   - Right-click Start Menu
   - Select "Command Prompt (Admin)" or "Windows Terminal (Admin)"

2. Update pip first:
   ```cmd
   python -m pip install --upgrade pip
   ```

3. Then install requirements:
   ```cmd
   pip install -r requirements.txt
   ```

---

### ❌ Error: "src/selfbot_webull.py not found"

**Cause**: Running batch file from wrong directory

**Solution**:
1. Make sure you're in the `EXE_Distribution` folder
2. Check that `src/` folder exists:
   ```cmd
   dir src
   ```
   You should see `selfbot_webull.py` and `setup_wizard.py`

3. Run `build_exe.bat` from the project root (where `src/` folder is)

---

### ❌ Error: "Failed to install pywin32"

**Cause**: Windows-specific package installation issue

**Solution**:
1. Install pywin32 manually as admin:
   ```cmd
   pip install --upgrade pywin32
   ```

2. Run post-install script:
   ```cmd
   python Scripts/pywin32_postinstall.py -install
   ```
   (If that fails, it's okay - try next step)

3. Try building again:
   ```cmd
   build_exe.bat
   ```

---

### ❌ Error: "ModuleNotFoundError" during build

**Cause**: Missing dependencies

**Solution**:
1. Install ALL dependencies first:
   ```cmd
   pip install -r requirements.txt
   ```

2. Install each manually if needed:
   ```cmd
   pip install discord.py-self
   pip install webull
   pip install requests
   pip install python-dotenv
   pip install pywin32
   pip install pyinstaller
   ```

3. Verify imports work:
   ```cmd
   python -c "import discord"
   python -c "import webull"
   python -c "import win32crypt"
   ```

4. Try building again

---

### ❌ Error: "VCRUNTIME140.dll is missing"

**Cause**: Missing Microsoft Visual C++ Redistributable

**Solution**:
1. Download and install:
   - [Visual C++ Redistributable (64-bit)](https://aka.ms/vs/17/release/vc_redist.x64.exe)
2. Restart your computer
3. Try building again

---

## Step-by-Step Debugging

If you're still having issues, follow these steps carefully:

### Step 1: Verify Python Installation
```cmd
python --version
```
✅ Should show: `Python 3.11.x` or higher  
❌ If not found: Install Python from python.org

### Step 2: Verify pip works
```cmd
pip --version
```
✅ Should show pip version  
❌ If not found: Reinstall Python with "Add to PATH" checked

### Step 3: Check folder structure
```cmd
dir
```
You should see:
- `src` folder
- `build_exe.bat`
- `requirements.txt`
- `config.ini.example`

### Step 4: Install dependencies one by one
```cmd
pip install discord.py-self
pip install webull
pip install requests
pip install python-dotenv
pip install pywin32
pip install pyinstaller
```

### Step 5: Test imports
```cmd
python -c "import discord; print('✅ discord ok')"
python -c "import webull; print('✅ webull ok')"
python -c "import win32crypt; print('✅ win32crypt ok')"
```
All should print ✅ without errors

### Step 6: Run build
```cmd
build_exe.bat
```

---

## Alternative: Manual Build Command

If the batch file still doesn't work, build manually:

```cmd
pyinstaller --onefile --name "DiscordTradingBot" --add-data "config.ini.example;." --hidden-import discord --hidden-import webull --hidden-import requests --hidden-import dotenv --hidden-import win32crypt --hidden-import setup_wizard --clean src/selfbot_webull.py
```

Then check:
```cmd
dir dist
```
You should see `DiscordTradingBot.exe`

---

## System Requirements Checklist

Make sure your system meets these requirements:

- ✅ Windows 10 or Windows 11
- ✅ Python 3.11 or higher (64-bit recommended)
- ✅ At least 500 MB free disk space
- ✅ Internet connection (to download packages)
- ✅ Administrator access (for installing packages)

---

## Quick Fixes Summary

| Problem | Quick Fix |
|---------|-----------|
| Batch file closes instantly | Run from Command Prompt, not double-click |
| Python not found | Install Python 3.11+, check "Add to PATH" |
| Permission denied | Run Command Prompt as Administrator |
| Missing modules | `pip install -r requirements.txt` |
| pywin32 error | `pip install --upgrade pywin32` |
| Wrong folder | Must be in `EXE_Distribution` folder |

---

## Still Not Working?

### Get Detailed Error Info:

The updated `build_exe.bat` now has error handling that will:
- ✅ Check if Python is installed
- ✅ Show Python version
- ✅ Check dependencies before building
- ✅ Display clear error messages
- ✅ Pause at errors so you can read them

Just make sure to **run it from Command Prompt** (not double-click)!

### Last Resort:

If nothing works, try this full clean install:

```cmd
REM Uninstall everything
pip uninstall discord discord.py discord.py-self webull pyinstaller -y

REM Clear pip cache
pip cache purge

REM Reinstall from requirements
pip install -r requirements.txt

REM Build
build_exe.bat
```

---

**Remember**: Always run `build_exe.bat` from Command Prompt so you can see what's happening!
