@echo off
REM FINAL BUILD - Excludes problematic packages
REM This fixes the matplotlib/numpy import error

echo ============================================================
echo Discord Trading Bot - FINAL BUILD (Fixed)
echo ============================================================
echo.

echo [1/4] Cleaning previous builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo.

echo [2/4] Building executable (excluding matplotlib)...
echo This should complete in 3-5 minutes...
echo.

python -m PyInstaller ^
    --onedir ^
    --name=DiscordTradingBot ^
    --console ^
    --clean ^
    --noconfirm ^
    --collect-all discord ^
    --collect-all webull ^
    --copy-metadata discord.py-self ^
    --exclude-module matplotlib ^
    --exclude-module matplotlib.pyplot ^
    --exclude-module PIL ^
    --exclude-module tkinter ^
    --exclude-module _tkinter ^
    --add-data "src;src" ^
    --add-data "gui_app;gui_app" ^
    --add-data "config.ini;." ^
    --hidden-import=flask ^
    --hidden-import=werkzeug ^
    src/selfbot_webull.py

if errorlevel 1 (
    echo [ERROR] PyInstaller build failed!
    pause
    exit /b 1
)
echo.

echo [3/4] Copying helper tools to distribution...
copy GET_DISCORD_TOKEN.html dist\DiscordTradingBot\ >nul
copy GET_WEBULL_TOKENS.html dist\DiscordTradingBot\ >nul
copy GET_MACHINE_ID.bat dist\DiscordTradingBot\ >nul
copy CUSTOMER_SETUP_GUIDE.txt dist\DiscordTradingBot\ >nul
copy dist_README.txt dist\DiscordTradingBot\README.txt >nul
copy config.ini dist\DiscordTradingBot\ >nul
echo   - Helper tools copied
echo   - Documentation copied
echo   - Configuration copied
echo.

echo [4/4] Build completed!
echo.

echo ============================================================
echo [SUCCESS] Build completed successfully!
============================================================
echo.
echo Output location: dist\DiscordTradingBot\
echo.
echo Distribution package includes:
echo   ✓ DiscordTradingBot.exe
echo   ✓ config.ini
echo   ✓ GET_DISCORD_TOKEN.html
echo   ✓ GET_WEBULL_TOKENS.html
echo   ✓ GET_MACHINE_ID.bat
echo   ✓ CUSTOMER_SETUP_GUIDE.txt
echo   ✓ README.txt
echo.
echo Next steps:
echo   1. Test the exe: cd dist\DiscordTradingBot ^&^& DiscordTradingBot.exe
echo   2. If it works, ZIP the entire dist\DiscordTradingBot\ folder
echo   3. Distribute to customers!
echo.
echo ============================================================
pause
