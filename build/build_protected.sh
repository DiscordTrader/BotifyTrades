#!/bin/bash
# Protected Build Script - PyArmor + PyInstaller (Linux/Mac)
# Creates obfuscated executable with machine-bound licensing

echo "============================================================"
echo "Discord Trading Bot - PROTECTED BUILD"
echo "============================================================"
echo ""

# Check PyArmor installation
if ! python3 -c "import pyarmor" 2>/dev/null; then
    echo "[ERROR] PyArmor not installed!"
    echo ""
    echo "Installing PyArmor..."
    pip3 install pyarmor
    echo ""
fi

# Check PyInstaller installation
if ! python3 -c "import PyInstaller" 2>/dev/null; then
    echo "[ERROR] PyInstaller not installed!"
    echo ""
    echo "Installing PyInstaller..."
    pip3 install pyinstaller
    echo ""
fi

echo "[1/5] Cleaning previous builds..."
rm -rf build dist obfuscated src_backup
echo ""

echo "[2/5] Obfuscating source code with PyArmor..."
echo "This protects your code from reverse engineering"
pyarmor gen --output obfuscated src/
if [ $? -ne 0 ]; then
    echo "[ERROR] PyArmor obfuscation failed!"
    exit 1
fi
echo ""

echo "[3/5] Copying obfuscated files..."
cp -r src src_backup
cp -r obfuscated/src/* src/
echo ""

echo "[4/5] Building protected executable..."
pyinstaller build_exe.spec --clean --noconfirm
if [ $? -ne 0 ]; then
    echo "[ERROR] PyInstaller build failed!"
    echo "Restoring original source..."
    rm -rf src
    mv src_backup src
    exit 1
fi
echo ""

echo "[5/5] Restoring original source code..."
rm -rf src
mv src_backup src
rm -rf obfuscated
echo ""

echo "============================================================"
echo "[SUCCESS] Protected build completed!"
echo "============================================================"
echo ""
echo "Output location: dist/DiscordTradingBot"
echo "Protection level: STRONG (PyArmor obfuscated + machine-bound licenses)"
echo ""
ls -lh dist/DiscordTradingBot
echo ""
echo "Next steps:"
echo "  1. Test the executable: cd dist && ./DiscordTradingBot"
echo "  2. Get customer's Machine ID"
echo "  3. Generate license: python3 generate_license_secure.py --customer NAME --machine ID --days 30"
echo "  4. Distribute executable + config.ini + license key"
echo ""
echo "============================================================"
