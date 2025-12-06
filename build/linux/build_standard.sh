#!/bin/bash
# ========================================================================
#   QuantumPulse - Linux Standard Build
#   Protection Level: Basic (PyInstaller bundling + UPX compression)
#   Estimated Protection: ~15-30 minutes to reverse engineer
#   
#   Note: PyInstaller 6.0+ removed --key AES encryption (ineffective)
#   Use PyArmor in hardened build for real code protection
# ========================================================================

set -e

echo ""
echo "========================================================================"
echo "  QuantumPulse Trading Bot - Linux Standard Build"
echo "  Protection: PyInstaller Bundling + UPX Compression"
echo "  Compatible with: PyInstaller 6.0+"
echo "========================================================================"
echo ""

# Change to project root
cd "$(dirname "$0")/../.."

# Check dependencies
echo "[1/5] Checking dependencies..."
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 not found. Please install Python 3.8+"
    exit 1
fi

if ! python3 -m pip show pyinstaller &> /dev/null; then
    echo "Installing PyInstaller..."
    python3 -m pip install pyinstaller pycryptodome
fi

# Clean previous builds
echo ""
echo "[2/5] Cleaning previous builds..."
rm -rf build/linux/dist_standard
rm -rf build/linux/build_temp

# Build with PyInstaller
echo ""
echo "[3/5] Building executable with PyInstaller..."
python3 -m PyInstaller --clean \
    --noconfirm \
    --onefile \
    --name "QuantumPulse_Trading_Bot" \
    --add-data "$(pwd)/gui_app:gui_app" \
    --add-data "$(pwd)/src:src" \
    --add-data "$(pwd)/config.ini.example:." \
    --add-data "$(pwd)/broker_sync_service.py:." \
    --paths "$(pwd)" \
    --hidden-import discord \
    --hidden-import webull \
    --hidden-import flask \
    --hidden-import openai \
    --hidden-import alpaca_py \
    --hidden-import ta \
    --hidden-import yfinance \
    --hidden-import broker_sync_service \
    --exclude-module pytest \
    --exclude-module unittest \
    --distpath "$(pwd)/build/linux/dist_standard" \
    --workpath "$(pwd)/build/linux/build_temp" \
    --specpath "$(pwd)/build/linux" \
    "$(pwd)/src/selfbot_webull.py"

# Strip symbols and compress
echo ""
echo "[4/6] Stripping debug symbols and compressing..."
strip --strip-all "build/linux/dist_standard/QuantumPulse_Trading_Bot"

if command -v upx &> /dev/null; then
    upx --best "build/linux/dist_standard/QuantumPulse_Trading_Bot"
else
    echo "UPX not found - skipping compression (install with: sudo apt install upx-ucl)"
fi

# Create distribution package
echo ""
echo "[5/6] Creating distribution package..."
mkdir -p "build/linux/dist_standard/config"
cp "config.ini.example" "build/linux/dist_standard/config.ini.example"
cp "GET_DISCORD_TOKEN.html" "build/linux/dist_standard/" 2>/dev/null || true
cp "GET_WEBULL_TOKENS.html" "build/linux/dist_standard/" 2>/dev/null || true

cat > "build/linux/dist_standard/run.sh" << 'EOF'
#!/bin/bash
echo "Starting QuantumPulse Trading Bot..."
cd "$(dirname "$0")"
./QuantumPulse_Trading_Bot
EOF

chmod +x "build/linux/dist_standard/run.sh"
chmod +x "build/linux/dist_standard/QuantumPulse_Trading_Bot"

echo ""
echo "========================================================================"
echo "  BUILD COMPLETE!"
echo "========================================================================"
echo "  Location: build/linux/dist_standard/"
echo "  Executable: QuantumPulse_Trading_Bot"
echo "  Protection Level: STANDARD (PyInstaller + UPX)"
echo "  Estimated Reverse Engineering Time: 15-30 minutes"
echo "  Note: For stronger protection, use build_hardened.sh (PyArmor BCC)"
echo "========================================================================"
echo ""
