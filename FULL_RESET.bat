@echo off
REM Complete reset for testing from scratch

echo ============================================================
echo COMPLETE BOT RESET
echo ============================================================
echo.

REM Delete credentials
del "%USERPROFILE%\.discord_trading_bot\credentials.dat" 2>nul
if exist "%USERPROFILE%\.discord_trading_bot" (
    rmdir /s /q "%USERPROFILE%\.discord_trading_bot"
    echo [1/3] Credentials deleted
) else (
    echo [1/3] No credentials found (already clean)
)

REM Delete activated license (server mode)
del "%USERPROFILE%\.tradingbot_license" 2>nul
echo [2/3] Activated license cleared

REM Delete .env if exists
if exist .env (
    del .env
    echo [3/3] .env file deleted
) else (
    echo [3/3] No .env file (already clean)
)

echo.
echo ============================================================
echo RESET COMPLETE!
echo ============================================================
echo.
echo The bot is now in completely fresh state.
echo Next run will trigger setup wizard.
echo.
echo Next steps:
echo   1. Get your Machine ID:
echo      python -c "from src.machine_fingerprint import get_machine_id; print(get_machine_id())"
echo.
echo   2. Generate license:
echo      python generate_license_secure.py --customer test_user --machine YOUR_ID --days 30
echo.
echo   3. Run bot:
echo      python src/selfbot_webull.py
echo.
echo   4. Paste license when prompted
echo.
pause
