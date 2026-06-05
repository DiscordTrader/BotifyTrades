@echo off
REM Build Discord Trading Bot as Windows EXE
REM This script creates a standalone executable

echo ========================================
echo Building Discord Trading Bot EXE
echo ========================================
echo.

REM Check if Python is installed
echo Checking for Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: Python is not installed or not in PATH!
    echo.
    echo Please install Python 3.11+ from python.org
    echo Make sure to check "Add Python to PATH" during installation
    echo.
    pause
    exit /b 1
)

python --version
echo.

REM Install dependencies
echo Installing dependencies...
echo This may take a minute...
echo.

pip install pyinstaller
pip install pywin32

echo.
echo Dependencies installed!
echo.

REM Temporarily rename config.ini files to prevent them from being bundled
REM Only config.ini.example should be bundled as a template
echo Temporarily moving config.ini files to prevent bundling...
if exist "src\config.ini" (
    move "src\config.ini" "src\config.ini.temp" >nul
)
if exist "config.ini" (
    move "config.ini" "config.ini.temp" >nul
)

REM Build the EXE using PyInstaller
echo Building executable...
echo This may take 2-3 minutes...
echo.

pyinstaller --onefile --name "DiscordTradingBot" ^
    --icon NONE ^
    --add-data "gui_app;gui_app" ^
    --add-data "src;src" ^
    --hidden-import "discord" ^
    --hidden-import "webull" ^
    --hidden-import "requests" ^
    --hidden-import "dotenv" ^
    --hidden-import "win32crypt" ^
    --hidden-import "setup_wizard" ^
    --hidden-import "flask" ^
    --hidden-import "flask_cors" ^
    --hidden-import "gui_app" ^
    --hidden-import "gui_app.app" ^
    --hidden-import "cryptography" ^
    --hidden-import "cryptography.fernet" ^
    --clean ^
    src/selfbot_webull.py

REM Restore config.ini files
echo Restoring config.ini files...
if exist "src\config.ini.temp" (
    move "src\config.ini.temp" "src\config.ini" >nul
)
if exist "config.ini.temp" (
    move "config.ini.temp" "config.ini" >nul
)

if errorlevel 1 (
    echo.
    echo ========================================
    echo BUILD FAILED!
    echo ========================================
    echo.
    echo Check the error messages above.
    echo Common issues:
    echo   - Missing dependencies: pip install -r requirements.txt
    echo   - src/selfbot_webull.py not found: run from project root
    echo.
    pause
    exit /b 1
)

echo.
echo Copying config template to dist folder...
if exist "config.ini.example" (
    copy "config.ini.example" "dist\" >nul
    echo ✓ Copied config.ini.example to dist\
) else (
    echo ⚠ WARNING: config.ini.example not found
)

echo.
echo ========================================
echo Build Complete!
echo ========================================
echo.
echo Your executable is located at:
echo   dist\DiscordTradingBot.exe
echo.
echo Next steps:
echo 1. Run create_distribution.bat to package for users
echo 2. Or test the EXE directly from dist folder
echo.
echo The EXE includes an interactive setup wizard that will
echo automatically run on first launch to collect credentials.
echo.
pause
