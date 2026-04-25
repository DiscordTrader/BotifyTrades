@echo off
setlocal

:: BotifyTradesv2 Auto-Save - Windows Task Scheduler Wrapper
:: Locates bash.exe and invokes autosave.sh

set "BASH_EXE="
if exist "C:\Program Files\Git\bin\bash.exe" set "BASH_EXE=C:\Program Files\Git\bin\bash.exe"
if exist "C:\Program Files (x86)\Git\bin\bash.exe" set "BASH_EXE=C:\Program Files (x86)\Git\bin\bash.exe"

if "%BASH_EXE%"=="" (
    where bash.exe >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        for /f "delims=" %%i in ('where bash.exe') do set "BASH_EXE=%%i"
    )
)

if "%BASH_EXE%"=="" (
    echo [%date% %time%] ERROR: bash.exe not found >> "%~dp0..\autosave_errors.log"
    exit /b 1
)

cd /d "%~dp0.."
"%BASH_EXE%" scripts/autosave.sh
exit /b %ERRORLEVEL%
