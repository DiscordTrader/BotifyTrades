@echo off
REM QuantumPulse Trading Bot - Windows Standard Build
REM Protection: 15-30 minutes to reverse engineer
REM This file is in the ROOT directory so it downloads with your project!

echo ================================================================================
echo   QuantumPulse Trading Bot - Windows Standard Build
echo ================================================================================
echo.
echo Protection Level: Standard (15-30 min to reverse)
echo Technologies: PyInstaller + UPX Compression
echo Output: QuantumPulse_Trading_Bot.exe
echo Note: PyInstaller 6.0+ removed bytecode encryption (use HARDENED build for obfuscation)
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found! Install Python 3.8+ first.
    pause
    exit /b 1
)

REM Check PyInstaller
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

echo.
echo [1/4] Cleaning previous builds...
if exist "dist_windows_standard" rmdir /s /q "dist_windows_standard"
if exist "build_temp_standard" rmdir /s /q "build_temp_standard"

echo.
echo [2/4] Building with PyInstaller...
pyinstaller --onefile ^
    --windowed ^
    --name "QuantumPulse_Trading_Bot" ^
    --icon NONE ^
    --paths "." ^
    --distpath "dist_windows_standard" ^
    --workpath "build_temp_standard" ^
    --specpath "." ^
    --hidden-import "discord" ^
    --hidden-import "webull" ^
    --hidden-import "flask" ^
    --hidden-import "alpaca" ^
    --hidden-import "openai" ^
    --hidden-import "broker_sync_service" ^
    --add-data "broker_sync_service.py;." ^
    --add-data "gui_app/templates;gui_app/templates" ^
    --add-data "gui_app/static;gui_app/static" ^
    --add-data "config.ini.example;." ^
    --exclude-module "pytest" ^
    --exclude-module "unittest" ^
    src/selfbot_webull.py

if errorlevel 1 (
    echo ERROR: Build failed!
    pause
    exit /b 1
)

echo.
echo [3/4] Compressing with UPX (if available)...
where upx >nul 2>&1
if not errorlevel 1 (
    upx --best "dist_windows_standard\QuantumPulse_Trading_Bot.exe"
) else (
    echo UPX not found, skipping compression (optional)
)

echo.
echo [4/4] Creating distribution package...
copy "config.ini.example" "dist_windows_standard\" >nul
copy "GET_DISCORD_TOKEN.html" "dist_windows_standard\" >nul 2>&1
copy "GET_WEBULL_TOKENS.html" "dist_windows_standard\" >nul 2>&1

REM Create run script
echo @echo off > "dist_windows_standard\RUN.bat"
echo QuantumPulse_Trading_Bot.exe >> "dist_windows_standard\RUN.bat"

REM Cleanup
if exist "build_temp_standard" rmdir /s /q "build_temp_standard"
if exist "QuantumPulse_Trading_Bot.spec" del "QuantumPulse_Trading_Bot.spec"

echo.
echo ================================================================================
echo   BUILD COMPLETE!
echo ================================================================================
echo.
echo Executable: dist_windows_standard\QuantumPulse_Trading_Bot.exe
echo Protection: 15-30 minutes to reverse engineer
echo.
echo Next steps:
echo 1. Find your exe in: dist_windows_standard\
echo 2. Copy config.ini.example to config.ini and configure
echo 3. Run the executable to start the bot
echo.
pause
