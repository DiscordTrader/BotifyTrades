@echo off
REM Test running the bot directly with Python (not built executable)
REM This will show if the issue is with the build or with the code itself

echo ================================================================================
echo   Testing QuantumPulse Bot - Direct Python Execution
echo ================================================================================
echo.
echo This runs the bot WITHOUT building an executable
echo If this works but the .exe doesn't, it's a build issue
echo If this also fails, it's a code issue
echo.
pause

cd src
python selfbot_webull.py

pause
