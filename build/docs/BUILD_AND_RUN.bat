@echo off
REM ===================================================================
REM QuantumPulse Discord Trading Bot - BUILD SCRIPT
REM ===================================================================
REM This is the ONE and ONLY build script you need
REM ===================================================================

echo.
echo ========================================================================================================
echo                          QUANTUMPULSE - EXE BUILD SCRIPT
echo ========================================================================================================
echo.

REM Check Python installation
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found! Please install Python 3.11+ first.
    pause
    exit /b 1
)

echo [STEP 1/4] Installing dependencies...
echo.
pip install pyinstaller==6.3.0 pywin32 --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller/pywin32
    pause
    exit /b 1
)
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)
echo [OK] Dependencies installed

echo.
echo [STEP 2/4] Cleaning previous build...
echo.
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo [OK] Cleaned

echo.
echo [STEP 3/4] Building .exe with PyInstaller...
echo.
pyinstaller --clean build_exe.spec
if errorlevel 1 (
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

echo.
echo [STEP 4/4] Copying configuration files...
echo.
copy /Y config.ini.example dist\config.ini >nul 2>&1
if not exist dist\config.ini (
    copy /Y config.ini dist\config.ini >nul 2>&1
)
echo [OK] Configuration files copied

echo.
echo ========================================================================================================
echo                          BUILD COMPLETE!
echo ========================================================================================================
echo.
echo Your distributable .exe is ready at:
echo    %CD%\dist\DiscordTradingBot.exe
echo.
echo Configuration file:
echo    %CD%\dist\config.ini
echo.
echo NEXT STEPS:
echo    1. Generate a license key:   python generate_license_activation.py --customer YourName --days 365
echo    2. Run the bot:              dist\DiscordTradingBot.exe
echo    3. Paste the license key when prompted
echo.
echo ========================================================================================================
echo.

pause
