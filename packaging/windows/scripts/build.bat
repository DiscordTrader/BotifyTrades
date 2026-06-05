@echo off
REM ========================================================================
REM   BotifyTrades - Windows Build (PyArmor Protected)
REM   Protection: PyArmor + PyInstaller + UPX Compression
REM   Note: NO GIT REQUIRED - version is read from upgrade/version.py
REM ========================================================================

echo.
echo ========================================================================
echo   BotifyTrades Trading Bot - Protected Build
echo   Protection: PyArmor Obfuscation + PyInstaller + UPX
echo ========================================================================
echo.

cd /d "%~dp0..\..\..\"

REM Check dependencies
echo [1/7] Checking dependencies...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3.8+
    pause
    exit /b 1
)

pip show pyarmor >nul 2>&1
if errorlevel 1 (
    echo Installing PyArmor...
    pip install pyarmor
)

pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

REM Backup original files
echo.
echo [2/7] Backing up original license files...
if not exist "packaging\windows\backup" mkdir "packaging\windows\backup"
copy "license\config\constants.py" "packaging\windows\backup\constants.py.bak" >nul
copy "license\client\manager_secure.py" "packaging\windows\backup\manager_secure.py.bak" >nul
copy "license\client\manager_activation.py" "packaging\windows\backup\manager_activation.py.bak" >nul

REM Obfuscate license files with PyArmor
echo.
echo [3/7] Obfuscating license files with PyArmor...
if exist "dist" rmdir /s /q "dist"

pyarmor gen -O dist_obf license\config\constants.py
if errorlevel 1 (
    echo ERROR: PyArmor obfuscation failed for constants.py
    goto :restore
)

pyarmor gen -O dist_obf license\client\manager_secure.py
if errorlevel 1 (
    echo ERROR: PyArmor obfuscation failed for manager_secure.py
    goto :restore
)

pyarmor gen -O dist_obf license\client\manager_activation.py
if errorlevel 1 (
    echo ERROR: PyArmor obfuscation failed for manager_activation.py
    goto :restore
)

REM Replace originals with obfuscated versions
echo.
echo [4/7] Replacing with obfuscated files...
copy /Y "dist_obf\constants.py" "license\config\constants.py" >nul
copy /Y "dist_obf\manager_secure.py" "license\client\manager_secure.py" >nul
copy /Y "dist_obf\manager_activation.py" "license\client\manager_activation.py" >nul

REM Copy PyArmor runtime (dynamic name detection with delayed expansion)
setlocal enabledelayedexpansion
set "PYARMOR_RUNTIME="
for /d %%d in (dist_obf\pyarmor_runtime_*) do (
    if not defined PYARMOR_RUNTIME (
        set "PYARMOR_RUNTIME=%%~nxd"
        echo Found PyArmor runtime: %%~nxd
    )
)
if not defined PYARMOR_RUNTIME (
    echo ERROR: No PyArmor runtime found in dist_obf!
    endlocal
    goto :restore
)
if not exist "license\!PYARMOR_RUNTIME!" mkdir "license\!PYARMOR_RUNTIME!"
xcopy /Y /E "dist_obf\!PYARMOR_RUNTIME!\*" "license\!PYARMOR_RUNTIME!\" >nul
endlocal

REM Clean previous builds
echo.
echo [5/7] Cleaning previous builds...
if exist "packaging\windows\dist" rmdir /s /q "packaging\windows\dist"
if exist "packaging\windows\build_temp" rmdir /s /q "packaging\windows\build_temp"
mkdir "packaging\windows\dist"

REM Build with PyInstaller using the pre-configured spec file
echo.
echo [6/7] Building executable with PyInstaller...

pyinstaller --clean --noconfirm ^
    --distpath "packaging\windows\dist" ^
    --workpath "packaging\windows\build_temp" ^
    packaging\windows\specs\botifytrades.spec

if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller build failed!
    goto :restore
)

REM Compress with UPX (optional)
echo.
echo [7/7] Compressing executable with UPX...
where upx >nul 2>&1
if not errorlevel 1 (
    upx --best "packaging\windows\dist\BotifyTrades.exe"
) else (
    echo UPX not found - skipping compression
)

REM Create distribution package
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
echo.
echo BUILD INFO:
echo - This build is protected with PyArmor obfuscation
) > "packaging\windows\dist\README.txt"

:restore
REM Restore original files
echo.
echo Restoring original license files...
copy /Y "packaging\windows\backup\constants.py.bak" "license\config\constants.py" >nul
copy /Y "packaging\windows\backup\manager_secure.py.bak" "license\client\manager_secure.py" >nul
copy /Y "packaging\windows\backup\manager_activation.py.bak" "license\client\manager_activation.py" >nul

REM Clean up
echo Cleaning up temporary files...
if exist "dist_obf" rmdir /s /q "dist_obf"
if exist "packaging\windows\build_temp" rmdir /s /q "packaging\windows\build_temp"
for /d %%d in (license\pyarmor_runtime_*) do rmdir /s /q "%%d"

echo.
echo ========================================================================
echo   BUILD COMPLETE!
echo ========================================================================
echo   Location: packaging\windows\dist\
echo   Executable: BotifyTrades.exe
echo   Protection: PyArmor + PyInstaller + UPX
echo ========================================================================
echo.

pause
