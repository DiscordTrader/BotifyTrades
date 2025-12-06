# Building Windows EXE

## Requirements
- Windows 10 or later
- Python 3.11 or higher
- pip (Python package installer)

## Build Instructions

### Option 1: Automated Build (Easiest)

1. Open Command Prompt or PowerShell
2. Navigate to the project folder:
   ```
   cd path\to\trading-bot
   ```
3. Run the build script:
   ```
   build_exe.bat
   ```
4. Wait for the build to complete (2-3 minutes)
5. Find your EXE in the `dist\` folder

### Option 2: Manual Build

1. Install PyInstaller:
   ```
   pip install pyinstaller
   ```

2. Run PyInstaller command:
   ```
   pyinstaller --onefile --name "DiscordTradingBot" --add-data "config.ini.example;." --hidden-import discord --hidden-import webull --hidden-import requests --hidden-import dotenv --clean src/selfbot_webull.py
   ```

3. Find your EXE in `dist\DiscordTradingBot.exe`

## Distribution Package

After building, create a distribution ZIP with:

```
TradingBot-v1.0/
├── DiscordTradingBot.exe
├── config.ini.example
├── EXE_SETUP.md
└── README.md
```

**Do NOT include:**
- Your personal `config.ini`
- `.position_cache.json`
- Any credential files
- Source code (`src/` folder)
- Build artifacts (`build/`, `__pycache__/`)

## Testing the EXE

Before distributing:

1. Test on a clean Windows machine (no Python installed)
2. Verify all dependencies are bundled
3. Test with fresh environment variables
4. Confirm signals are detected and processed
5. Check position monitoring works correctly

## File Size

The EXE will be approximately 15-20 MB due to bundled dependencies:
- Python runtime
- discord.py-self library
- webull library
- All other dependencies

This is normal for PyInstaller applications.

## Troubleshooting Build Issues

### "PyInstaller not found"
```
pip install pyinstaller
```

### "Module not found" errors
Add missing modules to the build command:
```
--hidden-import module_name
```

### EXE crashes immediately
- Check the console output for errors
- Ensure all dependencies are in requirements.txt
- Try building with `--debug all` flag for detailed logs

### Build takes too long
- Normal build time: 2-3 minutes
- First build is slower (downloads dependencies)
- Subsequent builds are faster

## Advanced: Custom Icon

To add a custom icon:

1. Create or download a `.ico` file
2. Update build_exe.bat, replace:
   ```
   --icon NONE
   ```
   with:
   ```
   --icon "path\to\your\icon.ico"
   ```

## Version Updates

When updating the bot:

1. Make your code changes
2. Update version number in code
3. Rebuild the EXE
4. Test thoroughly
5. Create new distribution ZIP
6. Document changes in release notes

---

**Note:** The EXE is Windows-only. For Mac/Linux, users should run the Python script directly (see LOCAL_SETUP.md).
