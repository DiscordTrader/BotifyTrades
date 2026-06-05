@echo off
REM Interactive environment variable setup for Windows
REM This makes it easier to set all required environment variables

echo ========================================
echo Discord Trading Bot - Setup Helper
echo ========================================
echo.
echo This script will help you set all required environment variables.
echo.
echo IMPORTANT: 
echo - Do NOT add quotes around your values
echo - Press Enter to skip optional values
echo - You must run the bot in THIS SAME window after setup
echo.
pause

echo.
echo ========================================
echo REQUIRED: Discord Token
echo ========================================
echo.
echo How to get your Discord token:
echo 1. Open Discord in Chrome/Firefox (not the app)
echo 2. Press F12 to open Developer Tools
echo 3. Go to Console tab
echo 4. Paste and run this code (it's safe):
echo.
echo (webpackChunkdiscord_app.push([[''],{},e=^>{m=[];for(let c in e.c)m.push(e.c[c])}]),m).find(m=^>m?.exports?.default?.getToken!==void 0).exports.default.getToken()
echo.
echo 5. Copy the token that appears
echo.
set /p discord_token="Enter your DISCORD_USER_TOKEN: "

echo.
echo ========================================
echo REQUIRED: Webull Trading PIN
echo ========================================
echo.
set /p webull_pin="Enter your WEBULL_TRADE_PIN (6 digits): "

echo.
echo ========================================
echo OPTIONAL: Webull Tokens (for fast login)
echo ========================================
echo.
echo If you have Webull tokens, enter them below.
echo Otherwise, press Enter to skip (you'll need username/password instead).
echo.
set /p webull_access="Enter WEBULL_ACCESS_TOKEN (or press Enter to skip): "
set /p webull_refresh="Enter WEBULL_REFRESH_TOKEN (or press Enter to skip): "
set /p webull_did="Enter WEBULL_DID (or press Enter to skip): "

echo.
echo ========================================
echo Setting Environment Variables...
echo ========================================
echo.

REM Set the variables
set DISCORD_USER_TOKEN=%discord_token%
set WEBULL_TRADE_PIN=%webull_pin%

if not "%webull_access%"=="" (
    set WEBULL_ACCESS_TOKEN=%webull_access%
    echo [OK] WEBULL_ACCESS_TOKEN set
)

if not "%webull_refresh%"=="" (
    set WEBULL_REFRESH_TOKEN=%webull_refresh%
    echo [OK] WEBULL_REFRESH_TOKEN set
)

if not "%webull_did%"=="" (
    set WEBULL_DID=%webull_did%
    echo [OK] WEBULL_DID set
)

echo [OK] DISCORD_USER_TOKEN set
echo [OK] WEBULL_TRADE_PIN set

echo.
echo ========================================
echo Validation
echo ========================================
echo.

REM Run validation
python test_setup.py

echo.
echo ========================================
echo Ready to Run!
echo ========================================
echo.
echo Your environment variables are set for THIS terminal window only.
echo.
set /p run_now="Do you want to start the bot now? (Y/N): "

if /i "%run_now%"=="Y" (
    echo.
    echo Starting bot...
    python src/selfbot_webull.py
) else (
    echo.
    echo To run the bot later, type in THIS SAME WINDOW:
    echo   python src/selfbot_webull.py
    echo.
    pause
)
