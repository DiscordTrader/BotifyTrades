#!/bin/bash
# ============================================================
# Ψ∿ QuantumPulse - Simple Linux Build Script
# Build Method: PyInstaller only (no obfuscation)
# Target: Ubuntu 20.04+ / Debian 11+
# ============================================================

set -e  # Exit on error

echo ""
echo "============================================================"
echo "   Ψ∿ QuantumPulse - SIMPLE BUILD (Linux)"
echo "============================================================"
echo ""
echo "Build Method: PyInstaller only (basic protection)"
echo "Build Time: ~2-3 minutes"
echo "Target: Ubuntu/Debian Linux"
echo ""

# Check Python installation
echo "[STEP 1/6] Checking Python installation..."
echo ""
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 not found!"
    echo "Install with: sudo apt install python3 python3-pip python3-venv"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1-2)
echo "✓ Python $PYTHON_VERSION found"

# Check required system packages
echo ""
echo "[STEP 2/6] Checking system dependencies..."
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

# Install build dependencies
echo ""
echo "[STEP 3/6] Installing build dependencies..."
echo ""
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install pyinstaller==6.3.0 --quiet
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to install PyInstaller"
    exit 1
fi
echo "✓ Build tools installed"

# Install bot dependencies
echo ""
echo "[STEP 4/6] Installing bot dependencies..."
echo ""
python3 -m pip install -r requirements.txt --quiet
if [ $? -ne 0 ]; then
    echo "[ERROR] Failed to install dependencies"
    exit 1
fi
echo "✓ Dependencies installed"

# Clean previous builds
echo ""
echo "[STEP 5/6] Cleaning previous builds..."
echo ""
rm -rf build dist
echo "✓ Build directories cleaned"

# Build executable
echo ""
echo "[STEP 6/6] Building Linux executable..."
echo "This may take 2-3 minutes..."
echo ""
pyinstaller build_linux.spec --clean --noconfirm
if [ $? -ne 0 ]; then
    echo ""
    echo "[ERROR] PyInstaller build failed!"
    exit 1
fi

echo "✓ Executable built successfully"

# Copy helper files
echo ""
echo "[DISTRIBUTION] Copying helper files..."
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

echo "✓ Helper files copied"

# Make executable runnable
chmod +x dist/DiscordTradingBot

echo ""
echo "============================================================"
echo "   ✅ BUILD COMPLETED SUCCESSFULLY!"
echo "============================================================"
echo ""
echo "Output: dist/DiscordTradingBot"
echo ""
echo "Protection Level: ⭐⭐ BASIC"
echo "  ✓ Compiled Python bytecode"
echo "  ✓ Hardware-bound licenses"
echo "  ✓ HMAC-signed activation keys"
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
echo "     ├── DiscordTradingBot (executable)"
echo "     ├── config.ini"
echo "     ├── GET_DISCORD_TOKEN.html"
echo "     ├── GET_WEBULL_TOKENS.html"
echo "     └── get_machine_id.sh"
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
echo "Option 3: Systemd Service (recommended)"
echo "  See: LINUX_DEPLOYMENT.md"
echo ""
echo "============================================================"
echo ""
