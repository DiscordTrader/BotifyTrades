@echo off
echo ============================================================
echo License Key Fixer - Workaround for Copy/Paste Issues
echo ============================================================
echo.
echo The :: separator is being corrupted during copy/paste.
echo Let's fix this by writing the key directly to a file.
echo.
echo Your license has two parts:
echo   1. Payload (base64 JSON)
echo   2. Signature (base64 HMAC)
echo.
echo ============================================================
pause
echo.

REM Create a temporary Python script to set the license
echo import os > temp_set_license.py
echo import sys >> temp_set_license.py
echo. >> temp_set_license.py
echo print("Enter the FIRST part (before the double colon):") >> temp_set_license.py
echo payload = input().strip() >> temp_set_license.py
echo print() >> temp_set_license.py
echo print("Enter the SECOND part (after the double colon):") >> temp_set_license.py
echo signature = input().strip() >> temp_set_license.py
echo. >> temp_set_license.py
echo # Reconstruct the license key with proper separator >> temp_set_license.py
echo license_key = payload + "::" + signature >> temp_set_license.py
echo. >> temp_set_license.py
echo print() >> temp_set_license.py
echo print("=" * 70) >> temp_set_license.py
echo print("RECONSTRUCTED LICENSE KEY:") >> temp_set_license.py
echo print("=" * 70) >> temp_set_license.py
echo print(license_key) >> temp_set_license.py
echo print() >> temp_set_license.py
echo print("Length:", len(license_key)) >> temp_set_license.py
echo print("Contains '::':", '::' in license_key) >> temp_set_license.py
echo print() >> temp_set_license.py
echo. >> temp_set_license.py
echo # Save to environment variable file >> temp_set_license.py
echo with open('.env', 'a') as f: >> temp_set_license.py
echo     f.write(f"\nLICENSE_KEY={license_key}\n") >> temp_set_license.py
echo. >> temp_set_license.py
echo print("✓ Saved to .env file") >> temp_set_license.py
echo print() >> temp_set_license.py
echo print("You can now use this license by setting it in:") >> temp_set_license.py
echo print("  1. config.ini under [License] section") >> temp_set_license.py
echo print("  2. Or it's already in .env file (loaded automatically)") >> temp_set_license.py

echo.
echo Running license key reconstructor...
echo.
python temp_set_license.py

del temp_set_license.py

echo.
echo ============================================================
echo Done! Your license key has been reconstructed and saved.
echo ============================================================
pause
