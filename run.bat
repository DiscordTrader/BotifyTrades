@echo off
REM Quick start script for Windows

echo ╔════════════════════════════════════════════════════════════╗
echo ║        Ψ∿ QuantumPulse - Local Launcher                   ║
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

REM Ask user to continue
set /p continue="Start QuantumPulse bot? (Y/N): "
if /i not "%continue%"=="Y" (
    echo.
    echo Exiting. Fix any errors above before running.
    pause
    exit /b 0
)

echo.
echo Starting bot...
echo Press Ctrl+C to stop
echo.

REM Run the bot
python src/selfbot_webull.py

pause
