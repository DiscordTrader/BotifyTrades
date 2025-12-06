@echo off
REM ========================================================================
REM   QuantumPulse - Windows Standard Build
REM   Protection Level: Basic (AES256 encryption + UPX compression)
REM   Estimated Protection: ~15-30 minutes to reverse engineer
REM ========================================================================

echo.
echo ========================================================================
echo   QuantumPulse Trading Bot - Windows Standard Build
echo   Protection: PyInstaller + AES256 Encryption + UPX Compression
echo ========================================================================
echo.

cd /d "%~dp0..\.."

REM Check dependencies
echo [1/6] Checking dependencies...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.8+
    pause
    exit /b 1
)

pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller pycryptodome
)

REM Clean previous builds
echo.
echo [2/6] Cleaning previous builds...
if exist "build\windows\dist_standard" rmdir /s /q "build\windows\dist_standard"
if exist "build\windows\build_temp" rmdir /s /q "build\windows\build_temp"

REM Generate random encryption key
echo.
echo [3/6] Generating encryption key...
set "ENCRYPTION_KEY=%RANDOM%%RANDOM%%RANDOM%%RANDOM%%RANDOM%%RANDOM%"
echo Encryption Key: %ENCRYPTION_KEY%

REM Build with PyInstaller
echo.
echo [4/6] Building executable with PyInstaller...
pyinstaller --clean ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "QuantumPulse_Trading_Bot" ^
    --key "%ENCRYPTION_KEY%" ^
    --add-data "gui_app;gui_app" ^
    --add-data "src;src" ^
    --add-data "config.ini.example;." ^
    --hidden-import discord ^
    --hidden-import webull ^
    --hidden-import flask ^
    --hidden-import openai ^
    --hidden-import alpaca_py ^
    --hidden-import ta ^
    --hidden-import yfinance ^
    --exclude-module pytest ^
    --exclude-module unittest ^
    --icon NONE ^
    --distpath "build\windows\dist_standard" ^
    --workpath "build\windows\build_temp" ^
    --specpath "build\windows" ^
    src\selfbot_webull.py

if errorlevel 1 (
    echo.
    echo ERROR: Build failed!
    pause
    exit /b 1
)

REM Compress with UPX (optional)
echo.
echo [5/6] Compressing executable with UPX...
where upx >nul 2>&1
if not errorlevel 1 (
    upx --best "build\windows\dist_standard\QuantumPulse_Trading_Bot.exe"
) else (
    echo UPX not found - skipping compression ^(download from https://upx.github.io/^)
)

REM Create distribution package
echo.
echo [6/6] Creating distribution package...
if not exist "build\windows\dist_standard\config" mkdir "build\windows\dist_standard\config"
copy "config.ini.example" "build\windows\dist_standard\config.ini.example" >nul
copy "GET_DISCORD_TOKEN.html" "build\windows\dist_standard\" >nul 2>&1
copy "GET_WEBULL_TOKENS.html" "build\windows\dist_standard\" >nul 2>&1

echo @echo off > "build\windows\dist_standard\RUN.bat"
echo echo Starting QuantumPulse Trading Bot... >> "build\windows\dist_standard\RUN.bat"
echo QuantumPulse_Trading_Bot.exe >> "build\windows\dist_standard\RUN.bat"

echo.
echo ========================================================================
echo   BUILD COMPLETE!
echo ========================================================================
echo   Location: build\windows\dist_standard\
echo   Executable: QuantumPulse_Trading_Bot.exe
echo   Protection Level: STANDARD (AES256 + UPX)
echo   Estimated Reverse Engineering Time: 15-30 minutes
echo ========================================================================
echo.

pause
