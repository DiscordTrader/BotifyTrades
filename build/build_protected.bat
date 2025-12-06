@echo off
REM Protected Build Script - PyArmor + PyInstaller
REM Creates obfuscated executable with machine-bound licensing

echo ============================================================
echo Discord Trading Bot - PROTECTED BUILD
echo ============================================================
echo.

REM Check PyArmor installation
python -c "import pyarmor" 2>nul
if errorlevel 1 (
    echo [ERROR] PyArmor not installed!
    echo.
    echo Installing PyArmor...
    pip install pyarmor
    echo.
)

REM Check PyInstaller installation
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [ERROR] PyInstaller not installed!
    echo.
    echo Installing PyInstaller...
    pip install pyinstaller
    echo.
)

echo [1/6] Cleaning previous builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist obfuscated rmdir /s /q obfuscated
if exist src_backup rmdir /s /q src_backup
echo.

echo [2/6] Backing up original source code...
echo Creating backup: src_backup\
xcopy src src_backup\ /E /I /Y /Q
if errorlevel 1 (
    echo [ERROR] Backup failed!
    pause
    exit /b 1
)
echo.

echo [3/6] Obfuscating source code with PyArmor...
echo This protects your code from reverse engineering
REM Set console to UTF-8 mode to handle emojis in source code
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
pyarmor gen --output obfuscated src/
if errorlevel 1 (
    echo [ERROR] PyArmor obfuscation failed!
    echo Restoring original source...
    rmdir /s /q src
    xcopy src_backup\ src\ /E /I /Y /Q
    rmdir /s /q src_backup obfuscated
    pause
    exit /b 1
)
echo.

echo [4/6] Replacing source with obfuscated version...
rmdir /s /q src
xcopy obfuscated\src\ src\ /E /I /Y /Q
echo.

echo [5/6] Building protected executable...
pyinstaller build_exe.spec --clean --noconfirm
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed!
    echo Restoring original source...
    rmdir /s /q src
    xcopy src_backup\ src\ /E /I /Y /Q
    rmdir /s /q src_backup obfuscated
    pause
    exit /b 1
)
echo.

echo [6/6] Restoring original source code...
rmdir /s /q src
xcopy src_backup\ src\ /E /I /Y /Q
rmdir /s /q src_backup obfuscated
echo.

echo ============================================================
echo [SUCCESS] Protected build completed!
echo ============================================================
echo.
echo Output location: dist\DiscordTradingBot.exe
echo Protection level: STRONG (PyArmor obfuscated + machine-bound licenses)
echo.
echo File size: 
dir dist\DiscordTradingBot.exe | find "DiscordTradingBot.exe"
echo.
echo Next steps:
echo   1. Test the exe: cd dist ^&^& DiscordTradingBot.exe
echo   2. Get customer's Machine ID
echo   3. Generate license: python generate_license_secure.py --customer NAME --machine ID --days 30
echo   4. Distribute exe + config.ini + license key
echo.
echo ============================================================
pause
