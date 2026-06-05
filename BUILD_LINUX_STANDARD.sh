#!/bin/bash
# QuantumPulse Trading Bot - Linux Standard Build
# Protection: 15-30 minutes to reverse engineer
# This file is in the ROOT directory so it downloads with your project!

echo "================================================================================"
echo "  QuantumPulse Trading Bot - Linux Standard Build"
echo "================================================================================"
echo ""
echo "Protection Level: Standard (15-30 min to reverse)"
echo "Technologies: PyInstaller + UPX + Strip"
echo "Output: QuantumPulse_Trading_Bot"
echo "Note: PyInstaller 6.0+ removed bytecode encryption (use HARDENED build for obfuscation)"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 not found! Install Python 3.8+ first."
    exit 1
fi

# Check PyInstaller
if ! pip3 show pyinstaller &> /dev/null; then
    echo "Installing PyInstaller..."
    pip3 install pyinstaller
fi

echo ""
echo "[1/5] Cleaning previous builds..."
rm -rf dist_linux_standard
rm -rf build_temp_standard

echo ""
echo "[2/5] Building with PyInstaller..."
python3 -m PyInstaller --onefile \
    --name "QuantumPulse_Trading_Bot" \
    --paths "." \
    --distpath "dist_linux_standard" \
    --workpath "build_temp_standard" \
    --specpath "." \
    --hidden-import "discord" \
    --hidden-import "webull" \
    --hidden-import "flask" \
    --hidden-import "alpaca" \
    --hidden-import "openai" \
    --hidden-import "broker_sync_service" \
    --hidden-import "tzdata" \
    --hidden-import "tastytrade" \
    --hidden-import "tastytrade.account" \
    --hidden-import "tastytrade.order" \
    --hidden-import "tastytrade.utils" \
    --collect-data "tzdata" \
    --collect-submodules "tastytrade" \
    --add-data "broker_sync_service.py:." \
    --add-data "gui_app/templates:gui_app/templates" \
    --add-data "gui_app/static:gui_app/static" \
    --add-data "config.ini.example:." \
    --exclude-module "pytest" \
    --exclude-module "unittest" \
    src/selfbot_webull.py || {
    echo "ERROR: Build failed!"
    exit 1
}

echo ""
echo "[3/5] Stripping debug symbols..."
strip "dist_linux_standard/QuantumPulse_Trading_Bot"

echo ""
echo "[4/5] Compressing with UPX (if available)..."
if command -v upx &> /dev/null; then
    upx --best "dist_linux_standard/QuantumPulse_Trading_Bot"
else
    echo "UPX not found, skipping compression (optional)"
fi

echo ""
echo "[5/5] Creating distribution package..."
cp config.ini.example dist_linux_standard/ 2>/dev/null || true
cp GET_DISCORD_TOKEN.html dist_linux_standard/ 2>/dev/null || true
cp GET_WEBULL_TOKENS.html dist_linux_standard/ 2>/dev/null || true
chmod +x dist_linux_standard/QuantumPulse_Trading_Bot

# Create run script
cat > dist_linux_standard/run.sh << 'EOF'
#!/bin/bash
./QuantumPulse_Trading_Bot
EOF
chmod +x dist_linux_standard/run.sh

# Cleanup
rm -rf build_temp_standard
rm -f QuantumPulse_Trading_Bot.spec

echo ""
echo "================================================================================"
echo "  BUILD COMPLETE!"
echo "================================================================================"
echo ""
echo "Executable: dist_linux_standard/QuantumPulse_Trading_Bot"
echo "Protection: 15-30 minutes to reverse engineer"
echo ""
echo "Next steps:"
echo "1. Find your binary in: dist_linux_standard/"
echo "2. Copy config.ini.example to config.ini and configure"
echo "3. Run: ./dist_linux_standard/QuantumPulse_Trading_Bot"
echo ""
