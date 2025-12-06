@echo off
REM ========================================================================
REM   BotifyTrades - Windows Standard Build
REM   Protection Level: Standard (UPX compression + PyInstaller packaging)
REM   Uses consolidated license/ module
REM   Note: --key encryption was removed in PyInstaller v6.0
REM ========================================================================

echo.
echo ========================================================================
echo   BotifyTrades Trading Bot - Windows Standard Build
echo   Protection: PyInstaller + UPX Compression
echo ========================================================================
echo.

cd /d "%~dp0..\..\..\"

REM Check dependencies
echo [1/5] Checking dependencies...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.8+
    pause
    exit /b 1
)

pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

REM Clean previous builds
echo.
echo [2/5] Cleaning previous builds...
if exist "packaging\windows\dist" rmdir /s /q "packaging\windows\dist"
if exist "packaging\windows\build_temp" rmdir /s /q "packaging\windows\build_temp"
mkdir "packaging\windows\dist"

REM Build with PyInstaller using the pre-configured spec file
echo.
echo [3/5] Building executable with PyInstaller...

pyinstaller --clean --noconfirm ^
    --distpath "packaging\windows\dist" ^
    --workpath "packaging\windows\build_temp" ^
    packaging\windows\specs\botifytrades.spec

if errorlevel 1 (
    echo.
    echo ERROR: Build failed!
    pause
    exit /b 1
)

REM Compress with UPX (optional)
echo.
echo [4/5] Compressing executable with UPX...
where upx >nul 2>&1
if not errorlevel 1 (
    upx --best "packaging\windows\dist\BotifyTrades.exe"
) else (
    echo UPX not found - skipping compression (optional)
)

REM Create distribution package
echo.
echo [5/5] Creating distribution package...
if not exist "packaging\windows\dist\config" mkdir "packaging\windows\dist\config"
copy "config.ini.example" "packaging\windows\dist\config.ini.example" >nul 2>&1
copy "GET_DISCORD_TOKEN.html" "packaging\windows\dist\" >nul 2>&1
copy "GET_WEBULL_TOKENS.html" "packaging\windows\dist\" >nul 2>&1

echo @echo off > "packaging\windows\dist\RUN.bat"
echo echo Starting BotifyTrades... >> "packaging\windows\dist\RUN.bat"
echo BotifyTrades.exe >> "packaging\windows\dist\RUN.bat"

REM Create README
(
echo BotifyTrades - Discord Trading Bot
echo ===================================
echo.
echo QUICK START:
echo 1. Run RUN.bat or BotifyTrades.exe
echo 2. Open http://localhost:5000 in your browser
echo 3. Complete the setup wizard
echo.
echo FIRST TIME SETUP:
echo - Create admin account via setup wizard
echo - Enter your license key
echo - Configure broker connections ^(Discord, Alpaca, Webull, IBKR^)
echo.
echo LICENSE:
echo - Obtain a license key from support
echo - Enter it in the License Management page
echo - License binds to this machine on first activation
echo.
echo SUPPORT:
echo - For issues, contact support with your Machine ID
echo - Machine ID can be found in the License Management page
) > "packaging\windows\dist\README.txt"

REM Clean up temp files
echo.
echo Cleaning up temporary files...
if exist "packaging\windows\build_temp" rmdir /s /q "packaging\windows\build_temp"

echo.
echo ========================================================================
echo   BUILD COMPLETE!
echo ========================================================================
echo   Location: packaging\windows\dist\
echo   Executable: BotifyTrades.exe
echo   Protection: Standard PyInstaller + UPX compression
echo ========================================================================
echo.

pause
