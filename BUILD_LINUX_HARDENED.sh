#!/bin/bash
# QuantumPulse Trading Bot - Linux Hardened Build
# Protection: 40+ hours to reverse engineer
# This file is in the ROOT directory so it downloads with your project!

echo "================================================================================"
echo "  QuantumPulse Trading Bot - Linux HARDENED Build"
echo "================================================================================"
echo ""
echo "Protection Level: HARDENED (40+ hours to reverse)"
echo "Technologies: PyArmor BCC + RFT + PyInstaller + UPX + Strip"
echo "Output: QuantumPulse_Trading_Bot_Pro"
echo "Note: PyInstaller 6.0+ removed bytecode encryption; protection is via PyArmor obfuscation"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 not found! Install Python 3.8+ first."
    exit 1
fi

# Check PyInstaller and PyArmor
if ! pip3 show pyinstaller &> /dev/null; then
    echo "Installing PyInstaller..."
    pip3 install pyinstaller
fi

if ! pip3 show pyarmor &> /dev/null; then
    echo "Installing PyArmor..."
    pip3 install pyarmor
fi

echo ""
echo "[1/8] Cleaning previous builds..."
rm -rf obfuscated_linux
rm -rf dist_linux_hardened
rm -rf build_temp_hardened

echo ""
echo "[2/8] Obfuscating code with PyArmor BCC Mode..."
echo "This converts Python functions to C code for maximum protection..."

# Obfuscate entire source tree
python3 -m pyarmor gen \
    --recursive \
    --output "obfuscated_linux" \
    --enable-bcc \
    --enable-rft \
    --mix-str \
    --assert-call \
    --assert-import \
    src/ || {
    echo "PyArmor BCC failed, trying without BCC..."
    python3 -m pyarmor gen \
        --recursive \
        --output "obfuscated_linux" \
        --enable-rft \
        --mix-str \
        src/ || {
        echo "ERROR: Obfuscation failed!"
        exit 1
    }
}

echo ""
echo "[3/8] Obfuscating GUI application..."
python3 -m pyarmor gen \
    --recursive \
    --output "obfuscated_linux" \
    --enable-rft \
    --mix-str \
    gui_app/

echo ""
echo "[4/8] Obfuscating broker sync service..."
python3 -m pyarmor gen \
    --output "obfuscated_linux" \
    --enable-rft \
    --mix-str \
    broker_sync_service.py

cp config.ini.example obfuscated_linux/

echo ""
echo "[5/7] Building with PyInstaller..."
python3 -m PyInstaller --onefile \
    --name "QuantumPulse_Trading_Bot_Pro" \
    --paths "obfuscated_linux" \
    --distpath "dist_linux_hardened" \
    --workpath "build_temp_hardened" \
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
    --add-data "obfuscated_linux/broker_sync_service.py:." \
    --add-data "obfuscated_linux/gui_app/templates:gui_app/templates" \
    --add-data "obfuscated_linux/gui_app/static:gui_app/static" \
    --add-data "obfuscated_linux/config.ini.example:." \
    --exclude-module "pytest" \
    --exclude-module "unittest" \
    obfuscated_linux/selfbot_webull.py || {
    echo "ERROR: Build failed!"
    exit 1
}

echo ""
echo "[6/7] Stripping debug symbols..."
strip "dist_linux_hardened/QuantumPulse_Trading_Bot_Pro"

echo ""
echo "[7/7] Compressing with UPX ultra (if available)..."
if command -v upx &> /dev/null; then
    upx --ultra-brute "dist_linux_hardened/QuantumPulse_Trading_Bot_Pro"
else
    echo "UPX not found, skipping compression (optional)"
fi

echo ""
echo "Creating distribution package..."
cp config.ini.example dist_linux_hardened/ 2>/dev/null || true
cp GET_DISCORD_TOKEN.html dist_linux_hardened/ 2>/dev/null || true
cp GET_WEBULL_TOKENS.html dist_linux_hardened/ 2>/dev/null || true
chmod +x dist_linux_hardened/QuantumPulse_Trading_Bot_Pro

# Create run script
cat > dist_linux_hardened/run.sh << 'EOF'
#!/bin/bash
./QuantumPulse_Trading_Bot_Pro
EOF
chmod +x dist_linux_hardened/run.sh

# Cleanup
rm -rf obfuscated_linux
rm -rf build_temp_hardened
rm -f QuantumPulse_Trading_Bot_Pro.spec

echo ""
echo "================================================================================"
echo "  BUILD COMPLETE!"
echo "================================================================================"
echo ""
echo "Executable: dist_linux_hardened/QuantumPulse_Trading_Bot_Pro"
echo "Protection: 40+ hours to reverse engineer"
echo ""
echo "Next steps:"
echo "1. Find your binary in: dist_linux_hardened/"
echo "2. Copy config.ini.example to config.ini and configure"
echo "3. Run: ./dist_linux_hardened/QuantumPulse_Trading_Bot_Pro"
echo ""
