@echo off
REM ALTERNATIVE BUILD - Direct PyInstaller (No Spec File)
REM Use this if build_simple.bat still has issues

echo ============================================================
echo Discord Trading Bot - ALTERNATIVE BUILD METHOD
echo ============================================================
echo.

REM Check PyInstaller installation
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [ERROR] PyInstaller not installed!
    echo.
    echo Installing PyInstaller...
    pip install pyinstaller
    echo.
)

echo [1/3] Cleaning previous builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo.

echo [2/3] Building executable with aggressive bundling...
echo This bundles EVERYTHING - may take 5-7 minutes and create larger .exe
echo.

python -m PyInstaller ^
    --onefile ^
    --name=DiscordTradingBot ^
    --console ^
    --clean ^
    --noconfirm ^
    --collect-all discord ^
    --collect-all webull ^
    --collect-all openai ^
    --collect-all ta ^
    --collect-all yfinance ^
    --collect-all aiohttp ^
    --copy-metadata discord.py-self ^
    --copy-metadata webull ^
    --add-data "src;src" ^
    --add-data "config.ini;." ^
    src/selfbot_webull.py

if errorlevel 1 (
    echo [ERROR] PyInstaller build failed!
    pause
    exit /b 1
)
echo.

echo [3/3] Copying helper tools to distribution...
copy GET_DISCORD_TOKEN.html dist\ >nul
copy GET_WEBULL_TOKENS.html dist\ >nul
copy GET_MACHINE_ID.bat dist\ >nul
copy CUSTOMER_SETUP_GUIDE.txt dist\ >nul
copy dist_README.txt dist\README.txt >nul
copy config.ini dist\ >nul
echo   - Helper tools copied
echo   - Documentation copied
echo   - Configuration copied
echo.

echo ============================================================
echo [SUCCESS] Alternative build completed!
echo ============================================================
echo.
echo Output location: dist\DiscordTradingBot.exe
echo Protection: Machine-bound licensing (hardware fingerprint)
echo.
echo NOTE: This build may be larger (100-150MB) because it includes
echo       ALL dependencies to ensure nothing is missing.
echo.
echo Distribution package includes:
echo   ✓ DiscordTradingBot.exe
echo   ✓ config.ini
echo   ✓ GET_DISCORD_TOKEN.html
echo   ✓ GET_WEBULL_TOKENS.html
echo   ✓ GET_MACHINE_ID.bat
echo   ✓ CUSTOMER_SETUP_GUIDE.txt
echo.
echo File size: 
dir dist\DiscordTradingBot.exe | find "DiscordTradingBot.exe"
echo.
echo Next steps:
echo   1. Test the exe: cd dist ^&^& DiscordTradingBot.exe
echo   2. If it works, distribute the entire dist\ folder
echo.
echo ============================================================
pause
