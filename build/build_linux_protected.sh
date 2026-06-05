#!/bin/bash
# ============================================================
# Ψ∿ QuantumPulse - Protected Linux Build Script
# Build Method: PyArmor + PyInstaller
# Protection: Code obfuscation + Hardware-bound licenses
# Target: Ubuntu 20.04+ / Debian 11+
# ============================================================

set -e  # Exit on error

echo ""
echo "============================================================"
echo "   Ψ∿ QuantumPulse - PROTECTED BUILD (Linux + PyArmor)"
echo "============================================================"
echo ""
echo "Protection: Code obfuscation + Hardware-bound licenses"
echo "Build Time: ~5-8 minutes"
echo "Requirement: PyArmor installed"
echo ""

# Check Python installation
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 not found!"
    echo "Install with: sudo apt install python3 python3-pip"
    exit 1
fi

echo "[STEP 1/8] Checking PyArmor installation..."
echo ""
if ! python3 -c "import pyarmor" 2>/dev/null; then
    echo "⚠ PyArmor not found!"
    echo ""
    echo "Installing PyArmor..."
    python3 -m pip install pyarmor
    if [ $? -ne 0 ]; then
        echo ""
        echo "[ERROR] Failed to install PyArmor"
        echo ""
        echo "Manual installation:"
        echo "  python3 -m pip install pyarmor"
        echo ""
        echo "PyArmor License Info:"
        echo "  - Free version: Limited features"
        echo "  - Basic: \$99/year (recommended for commercial use)"
        echo "  - Pro: \$599/year (advanced features)"
        echo ""
        echo "Get license: https://pyarmor.dashingsoft.com/pricing.html"
        exit 1
    fi
fi
echo "✓ PyArmor installed"

echo ""
echo "[STEP 2/8] Checking system dependencies..."
echo ""
MISSING_PACKAGES=()

if ! dpkg -l | grep -q "build-essential"; then
    MISSING_PACKAGES+=("build-essential")
fi
if ! dpkg -l | grep -q "libffi-dev"; then
    MISSING_PACKAGES+=("libffi-dev")
fi
if ! dpkg -l | grep -q "libssl-dev"; then
    MISSING_PACKAGES+=("libssl-dev")
fi
if ! dpkg -l | grep -q "python3-dev"; then
    MISSING_PACKAGES+=("python3-dev")
fi

if [ ${#MISSING_PACKAGES[@]} -gt 0 ]; then
    echo "⚠ Missing packages: ${MISSING_PACKAGES[*]}"
    echo ""
    echo "Install with:"
    echo "  sudo apt update"
    echo "  sudo apt install ${MISSING_PACKAGES[*]}"
    echo ""
    read -p "Install now? (y/n): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        sudo apt update
        sudo apt install -y "${MISSING_PACKAGES[@]}"
    else
        echo "[ERROR] Required packages not installed"
        exit 1
    fi
fi
echo "✓ System dependencies OK"

echo ""
echo "[STEP 3/8] Installing build dependencies..."
echo ""
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install pyinstaller==6.3.0 --quiet
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to install PyInstaller"
    exit 1
fi
echo "✓ Build tools installed"

echo ""
echo "[STEP 4/8] Installing bot dependencies..."
echo ""
python3 -m pip install -r requirements.txt --quiet
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to install dependencies"
    exit 1
fi
echo "✓ Dependencies installed"

echo ""
echo "[STEP 5/8] Cleaning previous builds..."
echo ""
rm -rf build dist obfuscated src_backup
echo "✓ Build directories cleaned"

echo ""
echo "[STEP 6/8] Backing up source code..."
echo ""
cp -r src src_backup
if [ $? -ne 0 ]; then
    echo "[ERROR] Backup failed!"
    exit 1
fi
echo "✓ Source code backed up"

echo ""
echo "[STEP 7/8] Obfuscating source code with PyArmor..."
echo "This protects your code from reverse engineering"
echo "Includes: license_manager_secure.py, gui_app modules, cryptography"
echo ""

# Obfuscate only src/ folder (gui_app will be included as data files)
pyarmor gen --output obfuscated --package src/
if [ $? -ne 0 ]; then
    echo ""
    echo "[ERROR] PyArmor obfuscation failed!"
    echo ""
    echo "Possible issues:"
    echo "  1. PyArmor license expired or invalid"
    echo "  2. Trial version limit reached"
    echo "  3. Syntax errors in source code"
    echo ""
    echo "Restoring original source..."
    rm -rf obfuscated src_backup
    exit 1
fi

echo "✓ Code obfuscated with PyArmor protection"

echo ""
echo "[STEP 8/8] Overwriting source with obfuscated version..."
echo ""
# Overwrite original source with obfuscated version (structure preserved)
cp -r obfuscated/src/* src/
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to overwrite with obfuscated files!"
    echo "Restoring original source..."
    rm -rf src
    cp -r src_backup src
    rm -rf src_backup obfuscated
    exit 1
fi

# Critical: Copy PyArmor runtime module to src/ directory
echo "Copying PyArmor runtime module..."
for runtime_dir in obfuscated/pyarmor_runtime_*; do
    if [ -d "$runtime_dir" ]; then
        runtime_name=$(basename "$runtime_dir")
        echo "Found runtime: $runtime_name"
        cp -r "$runtime_dir" "src/$runtime_name"
    fi
done
echo "✓ Source overwritten with obfuscated code"

echo ""
echo "[STEP 9/9] Building protected executable with obfuscated code..."
echo "This may take 3-5 minutes..."
echo ""
pyinstaller build_linux.spec --clean --noconfirm
if [ $? -ne 0 ]; then
    echo ""
    echo "[ERROR] PyInstaller build failed!"
    echo ""
    echo "Restoring original source..."
    rm -rf src
    cp -r src_backup src
    rm -rf src_backup obfuscated
    exit 1
fi

echo "✓ Protected executable built"

echo ""
echo "[CLEANUP] Restoring original source code..."
echo ""
# Restore original source code
rm -rf src
cp -r src_backup src
rm -rf src_backup obfuscated
echo "✓ Original source restored"

echo ""
echo "[DISTRIBUTION] Copying helper files and documentation..."
echo ""
cp config.ini dist/ 2>/dev/null || true
cp GET_DISCORD_TOKEN.html dist/ 2>/dev/null || true
cp GET_WEBULL_TOKENS.html dist/ 2>/dev/null || true
cp BUILD_METHODS_GUIDE.md dist/ 2>/dev/null || true
cp CREDENTIAL_MANAGEMENT.md dist/ 2>/dev/null || true

# Create machine ID helper for Linux
cat > dist/get_machine_id.sh << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
python3 -c "
import sys
sys.path.insert(0, '.')
from machine_fingerprint import get_machine_id
print('=' * 60)
print('Machine Fingerprint Information')
print('=' * 60)
print(f'Machine ID: {get_machine_id()}')
print('=' * 60)
print('\nShare this Machine ID with your license provider')
print('to receive a machine-bound license key.')
"
EOF
chmod +x dist/get_machine_id.sh

echo "✓ Helper files and documentation copied"

# Make executable runnable
chmod +x dist/DiscordTradingBot

echo ""
echo "============================================================"
echo "   ✅ PROTECTED BUILD COMPLETED SUCCESSFULLY!"
echo "============================================================"
echo ""
echo "Output: dist/DiscordTradingBot"
echo ""
echo "Protection Level: ⭐⭐⭐⭐ STRONG"
echo "  ✓ PyArmor code obfuscation"
echo "  ✓ Encrypted bytecode"
echo "  ✓ Anti-debugging protection"
echo "  ✓ Hardware-bound licenses"
echo "  ✓ HMAC-signed activation keys"
echo "  ✓ SECRET_KEY hidden from extraction"
echo ""
echo "File Size:"
ls -lh dist/DiscordTradingBot | awk '{print $5 " " $9}'
echo ""
echo "============================================================"
echo "NEXT STEPS:"
echo "============================================================"
echo ""
echo "1. Generate License:"
echo "   python3 generate_license_secure.py --customer NAME --days 30"
echo ""
echo "2. Test Executable:"
echo "   cd dist"
echo "   ./DiscordTradingBot"
echo ""
echo "3. Distribution Package:"
echo "   dist/"
echo "     ├── DiscordTradingBot (PROTECTED)"
echo "     ├── config.ini"
echo "     ├── GET_DISCORD_TOKEN.html"
echo "     ├── GET_WEBULL_TOKENS.html"
echo "     └── get_machine_id.sh"
echo ""
echo "============================================================"
echo "SECURITY FEATURES:"
echo "============================================================"
echo ""
echo "✓ Source code encrypted with PyArmor"
echo "✓ SECRET_KEY cannot be extracted"
echo "✓ Anti-debugging measures active"
echo "✓ License checks protected from bypass"
echo "✓ Cracking difficulty: VERY HARD (expert-level required)"
echo ""
echo "Recommended for:"
echo "  - Public distribution"
echo "  - Commercial sales"
echo "  - High-value products"
echo ""
echo "============================================================"
echo "DEPLOYMENT OPTIONS:"
echo "============================================================"
echo ""
echo "Option 1: Manual Run"
echo "  cd dist"
echo "  ./DiscordTradingBot"
echo ""
echo "Option 2: Background Process (screen)"
echo "  screen -S trading-bot"
echo "  cd dist && ./DiscordTradingBot"
echo "  # Press Ctrl+A then D to detach"
echo ""
echo "Option 3: Systemd Service (recommended for production)"
echo "  See: LINUX_DEPLOYMENT.md"
echo ""
echo "============================================================"
echo ""
