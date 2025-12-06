@echo off
REM QuantumPulse Trading Bot - Windows DEBUG Build (Shows Console Errors)
REM Use this to diagnose startup issues

echo ================================================================================
echo   QuantumPulse Trading Bot - Windows DEBUG Build
echo ================================================================================
echo.
echo This build SHOWS CONSOLE OUTPUT to help diagnose startup errors
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
echo [1/3] Cleaning previous DEBUG builds...
if exist "dist_windows_debug" rmdir /s /q "dist_windows_debug"
if exist "build_temp_debug" rmdir /s /q "build_temp_debug"

echo.
echo [2/3] Building DEBUG executable (WITH CONSOLE)...
pyinstaller --onefile ^
    --console ^
    --name "QuantumPulse_Trading_Bot_DEBUG" ^
    --icon NONE ^
    --paths "." ^
    --distpath "dist_windows_debug" ^
    --workpath "build_temp_debug" ^
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
echo [3/3] Creating distribution package...
copy "config.ini.example" "dist_windows_debug\" >nul
copy "GET_DISCORD_TOKEN.html" "dist_windows_debug\" >nul 2>&1
copy "GET_WEBULL_TOKENS.html" "dist_windows_debug\" >nul 2>&1

REM Cleanup
if exist "build_temp_debug" rmdir /s /q "build_temp_debug"
if exist "QuantumPulse_Trading_Bot_DEBUG.spec" del "QuantumPulse_Trading_Bot_DEBUG.spec"

echo.
echo ================================================================================
echo   DEBUG BUILD COMPLETE!
echo ================================================================================
echo.
echo Executable: dist_windows_debug\QuantumPulse_Trading_Bot_DEBUG.exe
echo.
echo IMPORTANT: This version shows a CONSOLE WINDOW with all error messages!
echo.
echo Next steps:
echo   1. Go to dist_windows_debug folder
echo   2. Double-click QuantumPulse_Trading_Bot_DEBUG.exe
echo   3. READ the error messages in the console window
echo   4. Copy the error text and share it
echo.
echo ================================================================================
pause
