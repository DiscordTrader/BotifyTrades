@echo off
echo ========================================
echo Quick Fix: Copy config.ini to dist
echo ========================================
echo.

REM Check if config.ini.example exists
if not exist "config.ini.example" (
    echo ERROR: config.ini.example not found in current directory!
    echo Please run this script from the project root folder.
    pause
    exit /b 1
)

REM Check if dist folder exists
if not exist "dist\" (
    echo ERROR: dist folder not found!
    echo Please build the EXE first with: build_exe.bat
    pause
    exit /b 1
)

REM Copy config.ini.example to dist
echo Copying config.ini.example to dist folder...
copy "config.ini.example" "dist\config.ini.example" >nul

echo ✓ Copied config.ini.example to dist\
echo.

REM If user has a real config.ini, copy that too
if exist "config.ini" (
    echo Found your config.ini - copying to dist as well...
    copy "config.ini" "dist\config.ini" >nul
    echo ✓ Copied config.ini to dist\
) else (
    echo Creating config.ini from template in dist folder...
    copy "dist\config.ini.example" "dist\config.ini" >nul
    echo ✓ Created dist\config.ini from template
    echo.
    echo ⚠ IMPORTANT: Edit dist\config.ini with your credentials before running the exe!
)

echo.
echo ========================================
echo Fix Complete!
echo ========================================
echo.
echo Your dist folder now has:
dir /b dist\*.ini 2>nul
echo.
echo Next step:
echo   1. Edit dist\config.ini with your credentials
echo   2. Run: dist\DiscordTradingBot.exe
echo.
pause
