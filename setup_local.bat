@echo off
echo ╔════════════════════════════════════════════════════════════════╗
echo ║         Ψ∿ QuantumPulse - Automatic Local Setup              ║
echo ║              Professional Discord Trading Bot                  ║
echo ╚════════════════════════════════════════════════════════════════╝
echo.

REM Check Python installation
echo [1/5] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ ERROR: Python not found!
    echo.
    echo Please install Python 3.11+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation
    pause
    exit /b 1
)
echo ✅ Python found

REM Check Python version
echo [2/5] Verifying Python version...
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo    Python version: %PYVER%
echo ✅ Version check passed

REM Install dependencies
echo [3/5] Installing dependencies (this may take 2-3 minutes)...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ❌ ERROR: Failed to install dependencies
    pause
    exit /b 1
)
echo ✅ Dependencies installed

REM Create config file if doesn't exist
echo [4/5] Setting up configuration...
if not exist "config.ini" (
    if exist "config.ini.example" (
        copy config.ini.example config.ini >nul
        echo ✅ Created config.ini from template
        echo.
        echo ⚠️  IMPORTANT: You must edit config.ini with your credentials!
        echo    - Discord token
        echo    - Webull credentials
        echo    - API keys
        echo    - License key
    ) else (
        echo ❌ WARNING: config.ini.example not found
    )
) else (
    echo ✅ config.ini already exists
)

echo.
echo [5/5] Setup complete! 🎉
echo.
echo ╔════════════════════════════════════════════════════════════════╗
echo ║                     NEXT STEPS                                 ║
echo ╠════════════════════════════════════════════════════════════════╣
echo ║ 1. Edit config.ini with your credentials                      ║
echo ║    - Use GET_DISCORD_TOKEN.html for Discord token             ║
echo ║    - Use GET_WEBULL_TOKENS.html for Webull credentials        ║
echo ║                                                                ║
echo ║ 2. Run the bot:                                                ║
echo ║    python src/selfbot_webull.py                                ║
echo ║                                                                ║
echo ║ 3. Open web GUI in browser:                                    ║
echo ║    http://127.0.0.1:5000                                       ║
echo ╚════════════════════════════════════════════════════════════════╝
echo.
pause
