@echo off
REM ============================================================
REM Ψ∿ QuantumPulse - Simple Build Script
REM Build Method: PyInstaller Only (No Obfuscation)
REM Protection: Hardware-bound licenses
REM ============================================================

echo.
echo ============================================================
echo    Ψ∿ QuantumPulse - SIMPLE BUILD
echo ============================================================
echo.
echo Protection: Hardware-bound licenses (no code obfuscation)
echo Build Time: ~3-5 minutes
echo.

REM Check Python installation
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found!
    echo Please install Python 3.11+ from python.org
    pause
    exit /b 1
)

echo [STEP 1/5] Installing build dependencies...
echo.
pip install pyinstaller==6.3.0 pywin32 --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller/pywin32
    pause
    exit /b 1
)
echo ✓ Build tools installed

echo.
echo [STEP 2/5] Installing bot dependencies...
echo.
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    echo Try: pip install -r requirements.txt
    pause
    exit /b 1
)
echo ✓ Dependencies installed

echo.
echo [STEP 3/5] Cleaning previous builds...
echo.
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo ✓ Build directory cleaned

echo.
echo [STEP 4/5] Building executable...
echo This may take 3-5 minutes...
echo.
pyinstaller build_exe.spec --clean --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller build failed!
    echo.
    echo Common fixes:
    echo   1. pip install -r requirements.txt
    echo   2. pip install pyinstaller --upgrade
    echo   3. Check Python version is 3.11+
    pause
    exit /b 1
)
echo ✓ Executable built

echo.
echo [STEP 5/5] Copying distribution files...
echo.
copy config.ini dist\ >nul 2>&1
copy GET_DISCORD_TOKEN.html dist\ >nul 2>&1
copy GET_WEBULL_TOKENS.html dist\ >nul 2>&1
copy GET_MACHINE_ID.bat dist\ >nul 2>&1
echo ✓ Helper files copied

echo.
echo ============================================================
echo    ✅ BUILD COMPLETED SUCCESSFULLY!
echo ============================================================
echo.
echo Output: dist\DiscordTradingBot.exe
echo.
echo Protection Level: ⭐⭐ BASIC
echo   ✓ Hardware-bound licenses
echo   ✓ HMAC-signed activation keys
echo   ⚠ Source code extractable (PyInstaller only)
echo.
echo File Size:
dir dist\DiscordTradingBot.exe | find "DiscordTradingBot.exe"
echo.
echo ============================================================
echo NEXT STEPS:
echo ============================================================
echo.
echo 1. Generate License:
echo    python generate_license_secure.py --customer NAME --days 30
echo.
echo 2. Test Executable:
echo    cd dist
echo    DiscordTradingBot.exe
echo.
echo 3. Distribution Package:
echo    dist\
echo      ├── DiscordTradingBot.exe
echo      ├── config.ini
echo      ├── GET_DISCORD_TOKEN.html
echo      ├── GET_WEBULL_TOKENS.html
echo      └── GET_MACHINE_ID.bat
echo.
echo ============================================================
echo CREDENTIAL STORAGE:
echo ============================================================
echo.
echo ✓ Credentials are NOT saved to config.ini
echo ✓ Asked at runtime on first launch
echo ✓ Encrypted using Windows DPAPI
echo ✓ Stored in: %%USERPROFILE%%\.discord_trading_bot\
echo ✓ Can be updated via Flask GUI Settings page
echo.
echo ============================================================
echo SECURITY NOTE:
echo ============================================================
echo.
echo ⚠ This build is vulnerable to reverse engineering
echo   - .exe can be extracted with pyinstxtractor
echo   - SECRET_KEY visible in bytecode
echo   - License checks can be bypassed
echo.
echo 💡 For public distribution, use: build_PyArmor.bat
echo    (Requires PyArmor - makes cracking 100x harder)
echo.
echo ============================================================
pause
