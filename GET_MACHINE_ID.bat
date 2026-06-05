@echo off
REM Quick script for customers to get their Machine ID
REM Can be distributed with the bot

echo.
echo ============================================================
echo Discord Trading Bot - Machine ID Lookup
echo ============================================================
echo.
echo Please wait, retrieving your Machine ID...
echo.

python -c "from src.machine_fingerprint import get_machine_id; print('YOUR MACHINE ID: ' + get_machine_id())"

if errorlevel 1 (
    echo.
    echo [ERROR] Could not retrieve Machine ID
    echo.
    echo Please ensure:
    echo  1. Python is installed
    echo  2. You are in the bot directory
    echo  3. src/machine_fingerprint.py exists
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo NEXT STEPS:
echo ============================================================
echo 1. Copy your Machine ID shown above
echo 2. Send it to your bot provider
echo 3. You will receive a license key
echo 4. Run DiscordTradingBot.exe and paste the license
echo ============================================================
echo.
pause
