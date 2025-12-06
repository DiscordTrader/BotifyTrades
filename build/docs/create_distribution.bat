@echo off
REM Create distribution package for Windows EXE
REM Run this after building the EXE

echo ========================================
echo Creating Distribution Package
echo ========================================
echo.

REM Check if EXE exists
if not exist "dist\DiscordTradingBot.exe" (
    echo ERROR: EXE not found!
    echo Please run build_exe.bat first to create the executable.
    echo.
    pause
    exit /b 1
)

REM Create distribution folder
set DIST_FOLDER=TradingBot-Distribution
if exist "%DIST_FOLDER%" (
    echo Removing old distribution folder...
    rmdir /s /q "%DIST_FOLDER%"
)

echo Creating distribution folder...
mkdir "%DIST_FOLDER%"

REM Copy essential files
echo Copying files...
copy "dist\DiscordTradingBot.exe" "%DIST_FOLDER%\" >nul
copy "config.ini.example" "%DIST_FOLDER%\" >nul

REM Copy helper tools
if exist "GET_DISCORD_TOKEN.html" copy "GET_DISCORD_TOKEN.html" "%DIST_FOLDER%\" >nul
if exist "GET_WEBULL_TOKENS.html" copy "GET_WEBULL_TOKENS.html" "%DIST_FOLDER%\" >nul
if exist "GET_MACHINE_ID.bat" copy "GET_MACHINE_ID.bat" "%DIST_FOLDER%\" >nul

REM Copy documentation
if exist "EXE_SETUP.md" copy "EXE_SETUP.md" "%DIST_FOLDER%\SETUP_GUIDE.txt" >nul
if exist "README.md" copy "README.md" "%DIST_FOLDER%\" >nul

REM SECURITY: Do NOT copy config.ini (it contains your credentials!)
REM Users must create their own config.ini from config.ini.example

echo.
echo ========================================
echo Distribution Package Created!
echo ========================================
echo.
echo Location: %DIST_FOLDER%\
echo.
echo Contents:
echo   - DiscordTradingBot.exe         (Main executable)
echo   - config.ini.example            (Configuration template)
echo   - GET_DISCORD_TOKEN.html        (Discord token extractor)
echo   - GET_WEBULL_TOKENS.html        (Webull credentials helper)
echo   - GET_MACHINE_ID.bat            (License machine ID tool)
echo   - SETUP_GUIDE.txt               (Setup instructions)
echo   - README.md                     (User documentation)
echo.
echo Creating ZIP package...
powershell -command "Compress-Archive -Path '%DIST_FOLDER%\*' -DestinationPath '%DIST_FOLDER%.zip' -Force"
if exist "%DIST_FOLDER%.zip" (
    echo ✓ Created: %DIST_FOLDER%.zip
) else (
    echo Note: ZIP creation failed. Manually compress the folder.
)
echo.
echo Next steps:
echo 1. Share %DIST_FOLDER%.zip with users
echo 2. Users extract and run DiscordTradingBot.exe
echo 3. Interactive setup wizard guides them through configuration
echo.
echo IMPORTANT: config.ini is NOT included to protect your credentials!
echo The exe will automatically look for config.ini in its directory.
echo.
pause
