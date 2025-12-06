@echo off
REM ============================================================
REM BotifyTrades - Windows Build Script with PyArmor Obfuscation
REM ============================================================

echo ============================================================
echo BotifyTrades Windows Build (with PyArmor Protection)
echo ============================================================
echo.

REM Get the directory where this script is located
set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..\..

cd /d %PROJECT_ROOT%

REM Step 1: Install dependencies
echo [1/5] Installing dependencies...
pip install pyinstaller pyarmor certifi requests --quiet
pip install -r requirements.txt --quiet
echo Done.
echo.

REM Step 2: Create obfuscated output directory
echo [2/5] Preparing obfuscation...
if exist "dist_obf" rmdir /s /q "dist_obf"
mkdir dist_obf
mkdir dist_obf\src
echo Done.
echo.

REM Step 3: Obfuscate license-related files with PyArmor
echo [3/5] Obfuscating license code with PyArmor...
pyarmor gen --output dist_obf/src src/license_client.py
pyarmor gen --output dist_obf/src src/license_manager.py
pyarmor gen --output dist_obf/src src/license_manager_secure.py
pyarmor gen --output dist_obf/src src/license_manager_activation.py
if exist "src\machine_fingerprint.py" (
    pyarmor gen --output dist_obf/src src/machine_fingerprint.py
)
echo Done.
echo.

REM Step 4: Copy obfuscated files back to src (backup originals first)
echo [4/5] Applying obfuscated code...
if not exist "src_backup" mkdir src_backup
copy /y src\license_client.py src_backup\ >nul
copy /y src\license_manager.py src_backup\ >nul
copy /y src\license_manager_secure.py src_backup\ >nul
copy /y src\license_manager_activation.py src_backup\ >nul

REM Copy obfuscated versions
copy /y dist_obf\src\license_client.py src\ >nul
copy /y dist_obf\src\license_manager.py src\ >nul
copy /y dist_obf\src\license_manager_secure.py src\ >nul
copy /y dist_obf\src\license_manager_activation.py src\ >nul

REM Copy PyArmor runtime to src
if exist "dist_obf\src\pyarmor_runtime_000000" (
    xcopy /s /y /q "dist_obf\src\pyarmor_runtime_000000" "src\pyarmor_runtime_000000\" >nul
)
echo Done.
echo.

REM Step 5: Build EXE with PyInstaller
echo [5/5] Building EXE with PyInstaller...
pyinstaller packaging/windows/specs/botifytrades.spec --distpath packaging/windows/dist --workpath packaging/windows/build_temp --noconfirm
echo Done.
echo.

REM Restore original source files
echo Restoring original source files...
copy /y src_backup\license_client.py src\ >nul
copy /y src_backup\license_manager.py src\ >nul
copy /y src_backup\license_manager_secure.py src\ >nul
copy /y src_backup\license_manager_activation.py src\ >nul
rmdir /s /q src_backup
rmdir /s /q dist_obf
if exist "src\pyarmor_runtime_000000" rmdir /s /q "src\pyarmor_runtime_000000"
echo Done.
echo.

echo ============================================================
echo BUILD COMPLETE!
echo ============================================================
echo.
echo EXE Location: packaging\windows\dist\BotifyTrades.exe
echo.
echo The license code has been obfuscated with PyArmor.
echo This makes reverse engineering significantly harder.
echo ============================================================

pause
