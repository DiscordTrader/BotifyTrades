@echo off
REM Quick start script for Windows - with auto-restart on crash

echo ╔════════════════════════════════════════════════════════════╗
echo ║              BotifyTrades - Local Launcher                 ║
echo ║          Professional Discord Trading Bot                  ║
echo ╚════════════════════════════════════════════════════════════╝
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo X Python is not installed!
    echo Please install Python 3.11+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [OK] Python found
python --version
echo.

REM Check if dependencies are installed
echo Checking dependencies...
python -c "import discord" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    echo This may take 2-3 minutes...
    echo.
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo ❌ ERROR: Failed to install dependencies
        echo.
        echo Try these fixes:
        echo 1. python -m pip install --upgrade pip
        echo 2. python -m pip install -r requirements.txt --no-cache-dir
        echo.
        pause
        exit /b 1
    )
    echo.
    echo ✅ Dependencies installed successfully
    echo.
)

REM Run validation script if it exists
if exist "test_setup.py" (
    echo Running setup validation...
    python test_setup.py
    if errorlevel 1 (
        echo.
        echo ⚠️  WARNING: Setup validation found issues
        echo You can continue, but the bot may not work correctly
        echo.
    )
    echo.
)

echo.
echo Starting bot with auto-restart enabled...
echo The bot will automatically restart if it crashes unexpectedly.
echo Press Ctrl+C to fully stop the bot.
echo.

:restart_loop
echo [%TIME%] Starting BotifyTrades...
python src/selfbot_webull.py
set EXIT_CODE=%ERRORLEVEL%

REM Exit code 0 = clean shutdown (Ctrl+C), do not restart
if %EXIT_CODE% EQU 0 (
    echo.
    echo Bot stopped cleanly.
    goto end
)

REM Any non-zero exit code = crash, auto-restart after delay
echo.
echo [%TIME%] Bot stopped unexpectedly (exit code %EXIT_CODE%). Restarting in 5 seconds...
echo Press Ctrl+C now to cancel restart.
timeout /t 5 /nobreak >nul
goto restart_loop

:end
pause
