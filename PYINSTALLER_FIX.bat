@echo off
REM EMERGENCY FIX - Reinstall everything and build
REM Use this if build keeps failing with "discord module not found"

echo ============================================================
echo Discord Trading Bot - EMERGENCY FIX
echo ============================================================
echo.
echo This will:
echo  1. Uninstall PyInstaller
echo  2. Uninstall discord.py-self
echo  3. Reinstall everything fresh
echo  4. Build with verified working method
echo.
pause

echo [1/5] Uninstalling old packages...
pip uninstall pyinstaller -y
pip uninstall discord.py-self -y
pip uninstall discord -y
echo.

echo [2/5] Reinstalling packages...
pip install discord.py-self==2.0.1
pip install pyinstaller==6.3.0
pip install -r requirements.txt
echo.

echo [3/5] Verifying installation...
python -c "import discord; print('Discord version:', discord.__version__)"
python -c "import PyInstaller; print('PyInstaller imported successfully')"
if errorlevel 1 (
    echo [ERROR] Installation verification failed!
    pause
    exit /b 1
)
echo.

echo [4/5] Cleaning old builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo.

echo [5/5] Building with emergency method...
python -m PyInstaller ^
    --onedir ^
    --name=DiscordTradingBot ^
    --console ^
    --noconfirm ^
    --paths=src ^
    --collect-all discord ^
    --collect-all webull ^
    --copy-metadata discord.py-self ^
    src/selfbot_webull.py

if errorlevel 1 (
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

echo.
echo Copying files to dist...
copy config.ini dist\DiscordTradingBot\ >nul
xcopy src dist\DiscordTradingBot\src\ /E /I /Y >nul
copy GET_DISCORD_TOKEN.html dist\DiscordTradingBot\ >nul
copy GET_WEBULL_TOKENS.html dist\DiscordTradingBot\ >nul
copy GET_MACHINE_ID.bat dist\DiscordTradingBot\ >nul
copy CUSTOMER_SETUP_GUIDE.txt dist\DiscordTradingBot\ >nul
copy dist_README.txt dist\DiscordTradingBot\README.txt >nul

echo.
echo ============================================================
echo [SUCCESS] Emergency build completed!
echo ============================================================
echo.
echo The .exe is in: dist\DiscordTradingBot\
echo.
echo To test:
echo   cd dist\DiscordTradingBot
echo   DiscordTradingBot.exe
echo.
echo To distribute: ZIP the entire dist\DiscordTradingBot\ folder
echo.
pause
