#!/bin/bash
# Protected Build Script - PyArmor + PyInstaller (Linux/Mac)
# Creates obfuscated executable with machine-bound licensing

echo "============================================================"
echo "BotifyTrades - PROTECTED BUILD (Licensed PyArmor)"
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

# ============================================================
# PyArmor License Registration
# ============================================================
echo "[0/6] Checking PyArmor license..."

# Check if already registered
if ! pyarmor -v 2>/dev/null | grep -qi "license"; then
    echo "PyArmor not registered. Checking for license files..."
    
    # Option 1: Use CI regfile if available (for automated builds)
    if ls pyarmor-ci-*.zip 1>/dev/null 2>&1; then
        echo "Found CI license file, registering..."
        pyarmor reg pyarmor-ci-*.zip
    # Option 2: Use registration file (for manual builds)
    elif ls pyarmor-regfile-*.zip 1>/dev/null 2>&1; then
        echo "Found registration file, registering..."
        pyarmor reg pyarmor-regfile-*.zip
    # Option 3: First-time registration with activation code
    elif ls pyarmor-regcode-*.txt 1>/dev/null 2>&1; then
        echo "Found activation code, performing initial registration..."
        pyarmor reg -p "BotifyTrades" pyarmor-regcode-*.txt
        echo ""
        echo "[IMPORTANT] Registration file created: pyarmor-regfile-*.zip"
        echo "Please backup this file for future builds!"
    else
        echo "[WARNING] No PyArmor license file found!"
        echo ""
        echo "To use licensed PyArmor, place one of these files in this directory:"
        echo "  - pyarmor-regcode-xxxx.txt (first-time activation)"
        echo "  - pyarmor-regfile-xxxx.zip (registered license)"
        echo "  - pyarmor-ci-xxxx.zip (CI/automated builds)"
        echo ""
        echo "Continuing with trial/basic PyArmor..."
    fi
else
    echo "PyArmor license already registered."
fi
echo ""

echo "[1/6] Cleaning previous builds..."
rm -rf build dist obfuscated src_backup
echo ""

echo "[2/6] Obfuscating source code with PyArmor..."
echo "This protects your code from reverse engineering"
pyarmor gen --output obfuscated src/
if [ $? -ne 0 ]; then
    echo "[ERROR] PyArmor obfuscation failed!"
    exit 1
fi
echo ""

echo "[3/6] Copying obfuscated files..."
cp -r src src_backup
cp -r obfuscated/src/* src/

# Critical: Copy PyArmor runtime module to src/ directory
echo "Copying PyArmor runtime module..."
for runtime_dir in obfuscated/pyarmor_runtime_*; do
    if [ -d "$runtime_dir" ]; then
        runtime_name=$(basename "$runtime_dir")
        echo "Found runtime: $runtime_name"
        cp -r "$runtime_dir" "src/$runtime_name"
    fi
done
echo ""

echo "[4/6] Building protected executable..."
pyinstaller build_exe.spec --clean --noconfirm
if [ $? -ne 0 ]; then
    echo "[ERROR] PyInstaller build failed!"
    echo "Restoring original source..."
    rm -rf src
    mv src_backup src
    exit 1
fi
echo ""

echo "[5/6] Restoring original source code..."
rm -rf src
mv src_backup src
rm -rf obfuscated
echo ""

echo "[6/6] Backing up registration file..."
if ls pyarmor-regfile-*.zip 1>/dev/null 2>&1; then
    mkdir -p license_backup
    cp pyarmor-regfile-*.zip license_backup/
    echo "Registration file backed up to license_backup/"
fi
echo ""

echo "============================================================"
echo "[SUCCESS] Protected build completed!"
echo "============================================================"
echo ""
echo "Output location: dist/BotifyTrades"
echo "Protection level: STRONG (PyArmor obfuscated + machine-bound licenses)"
echo ""
ls -lh dist/BotifyTrades 2>/dev/null || ls -lh dist/
echo ""
echo "Next steps:"
echo "  1. Test the executable: cd dist && ./BotifyTrades"
echo "  2. Get customer's Machine ID"
echo "  3. Generate license: python3 generate_license_secure.py --customer NAME --machine ID --days 30"
echo "  4. Distribute executable + config.ini + license key"
echo ""
echo "============================================================"
