@echo off
REM Protected Build Script - PyArmor + PyInstaller
REM Creates obfuscated executable with machine-bound licensing

echo ============================================================
echo BotifyTrades - PROTECTED BUILD (Licensed PyArmor)
echo ============================================================
echo.

REM Check PyArmor installation
python -c "import pyarmor" 2>nul
if errorlevel 1 (
    echo [ERROR] PyArmor not installed!
    echo.
    echo Installing PyArmor...
    pip install pyarmor
    echo.
)

REM Check PyInstaller installation
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [ERROR] PyInstaller not installed!
    echo.
    echo Installing PyInstaller...
    pip install pyinstaller
    echo.
)

REM ============================================================
REM PyArmor License Registration
REM ============================================================
echo [0/7] Checking PyArmor license...

REM Check if already registered
pyarmor -v 2>nul | findstr /i "license" >nul
if errorlevel 1 (
    echo PyArmor not registered. Checking for license files...
    
    REM Option 1: Use CI regfile if available (for automated builds)
    if exist "pyarmor-ci-*.zip" (
        echo Found CI license file, registering...
        for %%f in (pyarmor-ci-*.zip) do pyarmor reg "%%f"
    ) else if exist "pyarmor-regfile-*.zip" (
        REM Option 2: Use registration file (for manual builds)
        echo Found registration file, registering...
        for %%f in (pyarmor-regfile-*.zip) do pyarmor reg "%%f"
    ) else if exist "pyarmor-regcode-*.txt" (
        REM Option 3: First-time registration with activation code
        echo Found activation code, performing initial registration...
        for %%f in (pyarmor-regcode-*.txt) do (
            pyarmor reg -p "BotifyTrades" "%%f"
            echo.
            echo [IMPORTANT] Registration file created: pyarmor-regfile-*.zip
            echo Please backup this file for future builds!
        )
    ) else (
        echo [WARNING] No PyArmor license file found!
        echo.
        echo To use licensed PyArmor, place one of these files in this directory:
        echo   - pyarmor-regcode-xxxx.txt (first-time activation)
        echo   - pyarmor-regfile-xxxx.zip (registered license)
        echo   - pyarmor-ci-xxxx.zip (CI/automated builds)
        echo.
        echo Continuing with trial/basic PyArmor...
    )
) else (
    echo PyArmor license already registered.
)
echo.

echo [1/7] Cleaning previous builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist obfuscated rmdir /s /q obfuscated
if exist src_backup rmdir /s /q src_backup
echo.

echo [2/6] Backing up original source code...
echo Creating backup: src_backup\
xcopy src src_backup\ /E /I /Y /Q
if errorlevel 1 (
    echo [ERROR] Backup failed!
    pause
    exit /b 1
)
echo.

echo [3/6] Obfuscating source code with PyArmor...
echo This protects your code from reverse engineering
REM Set console to UTF-8 mode to handle emojis in source code
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
pyarmor gen --output obfuscated src/
if errorlevel 1 (
    echo [ERROR] PyArmor obfuscation failed!
    echo Restoring original source...
    rmdir /s /q src
    xcopy src_backup\ src\ /E /I /Y /Q
    rmdir /s /q src_backup obfuscated
    pause
    exit /b 1
)
echo.

echo [4/6] Replacing source with obfuscated version...
rmdir /s /q src
xcopy obfuscated\src\ src\ /E /I /Y /Q

REM Critical: Copy PyArmor runtime module to src/ directory
echo Copying PyArmor runtime module...
for /d %%d in (obfuscated\pyarmor_runtime_*) do (
    echo Found runtime: %%~nxd
    xcopy "%%d" "src\%%~nxd\" /E /I /Y /Q >nul
)
echo.

echo [5/6] Building protected executable...
pyinstaller build_exe.spec --clean --noconfirm
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed!
    echo Restoring original source...
    rmdir /s /q src
    xcopy src_backup\ src\ /E /I /Y /Q
    rmdir /s /q src_backup obfuscated
    pause
    exit /b 1
)
echo.

echo [6/6] Restoring original source code...
rmdir /s /q src
xcopy src_backup\ src\ /E /I /Y /Q
rmdir /s /q src_backup obfuscated
echo.

echo [7/7] Backing up registration file...
if exist "pyarmor-regfile-*.zip" (
    if not exist license_backup mkdir license_backup
    copy pyarmor-regfile-*.zip license_backup\ >nul
    echo Registration file backed up to license_backup\
)
echo.

echo ============================================================
echo [SUCCESS] Protected build completed!
echo ============================================================
echo.
echo Output location: dist\BotifyTrades.exe
echo Protection level: STRONG (PyArmor obfuscated + machine-bound licenses)
echo.
echo File size: 
dir dist\BotifyTrades.exe 2>nul | find "BotifyTrades.exe"
if errorlevel 1 dir dist\ | find ".exe"
echo.
echo Next steps:
echo   1. Test the exe: cd dist ^&^& BotifyTrades.exe
echo   2. Get customer's Machine ID
echo   3. Generate license: python generate_license_secure.py --customer NAME --machine ID --days 30
echo   4. Distribute exe + config.ini + license key
echo.
echo ============================================================
pause
