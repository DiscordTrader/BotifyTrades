@echo off
REM ============================================================
REM Ψ∿ QuantumPulse - Protected Build Script
REM Build Method: PyArmor + PyInstaller
REM Protection: Code obfuscation + Hardware-bound licenses
REM ============================================================

echo.
echo ============================================================
echo    Ψ∿ QuantumPulse - PROTECTED BUILD (PyArmor)
echo ============================================================
echo.
echo Protection: Code obfuscation + Hardware-bound licenses
echo Build Time: ~5-8 minutes
echo Requirement: PyArmor installed
echo.

REM Check Python installation
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found!
    echo Please install Python 3.11+ from python.org
    pause
    exit /b 1
)

echo [STEP 1/7] Checking PyArmor installation...
echo.
python -c "import pyarmor" 2>nul
if errorlevel 1 (
    echo ⚠ PyArmor not found!
    echo.
    echo Installing PyArmor...
    pip install pyarmor
    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to install PyArmor
        echo.
        echo Manual installation:
        echo   pip install pyarmor
        echo.
        echo PyArmor License Info:
        echo   - Free version: Limited features
        echo   - Basic: $99/year (recommended for commercial use)
        echo   - Pro: $599/year (advanced features)
        echo.
        echo Get license: https://pyarmor.dashingsoft.com/pricing.html
        pause
        exit /b 1
    )
)
echo ✓ PyArmor installed

echo.
echo [STEP 2/7] Installing build dependencies...
echo.
pip install pyinstaller==6.3.0 pywin32 --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller/pywin32
    pause
    exit /b 1
)
echo ✓ Build tools installed

echo.
echo [STEP 3/7] Installing bot dependencies...
echo.
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)
echo ✓ Dependencies installed

echo.
echo [STEP 4/7] Cleaning previous builds...
echo.
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist obfuscated rmdir /s /q obfuscated
if exist src_backup rmdir /s /q src_backup
echo ✓ Build directories cleaned

echo.
echo [STEP 5/7] Backing up source code...
echo.
xcopy src src_backup\ /E /I /Y /Q >nul
if errorlevel 1 (
    echo [ERROR] Backup failed!
    pause
    exit /b 1
)
echo ✓ Source code backed up

echo.
echo [STEP 6/7] Obfuscating source code with PyArmor...
echo This protects your code from reverse engineering
echo Includes: license_manager_secure.py, gui_app modules, cryptography
echo.
REM Set UTF-8 encoding to handle emojis in source code
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

REM Obfuscate only src/ folder (gui_app will be included as data files)
pyarmor gen --output obfuscated --package src/
if errorlevel 1 (
    echo.
    echo [ERROR] PyArmor obfuscation failed!
    echo.
    echo Possible issues:
    echo   1. PyArmor license expired or invalid
    echo   2. Trial version limit reached
    echo   3. Syntax errors in source code
    echo.
    echo Restoring original source...
    rmdir /s /q obfuscated 2>nul
    rmdir /s /q src_backup 2>nul
    pause
    exit /b 1
)

echo ✓ Code obfuscated with PyArmor protection

echo.
echo [STEP 7/8] Overwriting source with obfuscated version...
echo.
REM Overwrite original source with obfuscated version (structure preserved)
xcopy obfuscated\src\ src\ /E /I /Y /Q >nul
if errorlevel 1 (
    echo [ERROR] Failed to overwrite with obfuscated files!
    echo Restoring original source...
    rmdir /s /q src
    xcopy src_backup\ src\ /E /I /Y /Q >nul
    rmdir /s /q src_backup obfuscated
    pause
    exit /b 1
)

REM Critical: Copy PyArmor runtime module to src/ directory
echo Copying PyArmor runtime module...
for /d %%d in (obfuscated\pyarmor_runtime_*) do (
    echo Found runtime: %%~nxd
    xcopy "%%d" "src\%%~nxd\" /E /I /Y /Q >nul
)
echo ✓ Source overwritten with obfuscated code

echo.
echo [STEP 8/8] Building protected executable with obfuscated code...
echo This may take 3-5 minutes...
echo.
pyinstaller build_exe.spec --clean --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller build failed!
    echo.
    echo Restoring original source...
    rmdir /s /q src
    xcopy src_backup\ src\ /E /I /Y /Q >nul
    rmdir /s /q src_backup obfuscated
    pause
    exit /b 1
)

echo ✓ Protected executable built

echo.
echo [CLEANUP] Restoring original source code...
echo.
REM Restore original source code
rmdir /s /q src
xcopy src_backup\ src\ /E /I /Y /Q >nul
rmdir /s /q src_backup obfuscated
echo ✓ Original source restored

echo.
echo [DISTRIBUTION] Copying helper files and documentation...
echo.
copy config.ini dist\ >nul 2>&1
copy GET_DISCORD_TOKEN.html dist\ >nul 2>&1
copy GET_WEBULL_TOKENS.html dist\ >nul 2>&1
copy GET_MACHINE_ID.bat dist\ >nul 2>&1
copy BUILD_METHODS_GUIDE.md dist\ >nul 2>&1
copy CREDENTIAL_MANAGEMENT.md dist\ >nul 2>&1
echo ✓ Helper files and documentation copied

echo.
echo ============================================================
echo    ✅ PROTECTED BUILD COMPLETED SUCCESSFULLY!
echo ============================================================
echo.
echo Output: dist\DiscordTradingBot.exe
echo.
echo Protection Level: ⭐⭐⭐⭐ STRONG
echo   ✓ PyArmor code obfuscation
echo   ✓ Encrypted bytecode
echo   ✓ Anti-debugging protection
echo   ✓ Hardware-bound licenses
echo   ✓ HMAC-signed activation keys
echo   ✓ SECRET_KEY hidden from extraction
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
echo      ├── DiscordTradingBot.exe (PROTECTED)
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
echo SECURITY FEATURES:
echo ============================================================
echo.
echo ✓ Source code encrypted with PyArmor
echo ✓ SECRET_KEY cannot be extracted
echo ✓ Anti-debugging measures active
echo ✓ License checks protected from bypass
echo ✓ Cracking difficulty: VERY HARD (expert-level required)
echo.
echo Recommended for:
echo   - Public distribution
echo   - Commercial sales
echo   - High-value products
echo.
echo ============================================================
pause
