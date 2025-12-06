@echo off
REM Windows build script for Discord Trading Bot
REM This script builds the bot into a standalone .exe file

echo ============================================================
echo Discord Trading Bot - Build Script
echo ============================================================
echo.

REM Check if PyInstaller is installed
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [ERROR] PyInstaller not found! Installing...
    pip install pyinstaller
    echo.
)

echo [BUILD] Starting build process...
echo.

REM Clean previous builds
echo [BUILD] Cleaning previous builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo.

REM Build the executable
echo [BUILD] Building executable with PyInstaller...
pyinstaller build_exe.spec --clean --noconfirm
echo.

REM Check if build succeeded
if not exist "dist\DiscordTradingBot.exe" (
    echo [ERROR] Build failed! Check errors above.
    pause
    exit /b 1
)

echo ============================================================
echo [SUCCESS] Build completed successfully!
echo ============================================================
echo.
echo Distributable package location: dist\
echo.
echo Package contents:
echo   - DiscordTradingBot.exe  (Main executable)
echo   - config.ini             (Configuration file)
echo.
echo Next steps:
echo   1. Test the exe: cd dist ^&^& DiscordTradingBot.exe
echo   2. Generate license keys for customers
echo   3. Distribute the exe + config.ini + license key
echo.
echo ============================================================
pause
