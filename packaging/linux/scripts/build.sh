#!/bin/bash
# ========================================================================
#   BotifyTrades - Linux Build (PyArmor Protected)
#   Protection: PyArmor + PyInstaller + UPX Compression
#   Note: NO GIT REQUIRED - version is read from upgrade/version.py
# ========================================================================

echo ""
echo "========================================================================"
echo "  BotifyTrades Trading Bot - Protected Build"
echo "  Protection: PyArmor Obfuscation + PyInstaller + UPX"
echo "========================================================================"
echo ""

# Navigate to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$PROJECT_ROOT"

echo "Project root: $PROJECT_ROOT"

# Check dependencies
echo "[1/7] Checking dependencies..."
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 not found. Please install Python 3.8+"
    exit 1
fi

echo "Python version: $(python3 --version)"

if ! pip show pyarmor &> /dev/null; then
    echo "Installing PyArmor..."
    pip install pyarmor
fi

if ! pip show pyinstaller &> /dev/null; then
    echo "Installing PyInstaller..."
    pip install pyinstaller
fi

# Backup original files
echo ""
echo "[2/7] Backing up original license files..."
mkdir -p packaging/linux/backup
cp "license/config/constants.py" "packaging/linux/backup/constants.py.bak"
cp "license/client/manager_secure.py" "packaging/linux/backup/manager_secure.py.bak"
cp "license/client/manager_activation.py" "packaging/linux/backup/manager_activation.py.bak"

# Function to restore files on error or completion
restore_files() {
    echo ""
    echo "Restoring original license files..."
    cp -f "packaging/linux/backup/constants.py.bak" "license/config/constants.py"
    cp -f "packaging/linux/backup/manager_secure.py.bak" "license/client/manager_secure.py"
    cp -f "packaging/linux/backup/manager_activation.py.bak" "license/client/manager_activation.py"
    
    # Clean up
    echo "Cleaning up temporary files..."
    rm -rf dist_obf
    rm -rf packaging/linux/build_temp
    rm -rf license/pyarmor_runtime_*
}

# Set trap to restore files on exit
trap restore_files EXIT

# Obfuscate license files with PyArmor
echo ""
echo "[3/7] Obfuscating license files with PyArmor..."
rm -rf dist_obf

pyarmor gen -O dist_obf license/config/constants.py
if [ $? -ne 0 ]; then
    echo "ERROR: PyArmor obfuscation failed for constants.py"
    exit 1
fi

pyarmor gen -O dist_obf license/client/manager_secure.py
if [ $? -ne 0 ]; then
    echo "ERROR: PyArmor obfuscation failed for manager_secure.py"
    exit 1
fi

pyarmor gen -O dist_obf license/client/manager_activation.py
if [ $? -ne 0 ]; then
    echo "ERROR: PyArmor obfuscation failed for manager_activation.py"
    exit 1
fi

# Replace originals with obfuscated versions
echo ""
echo "[4/7] Replacing with obfuscated files..."
cp -f "dist_obf/constants.py" "license/config/constants.py"
cp -f "dist_obf/manager_secure.py" "license/client/manager_secure.py"
cp -f "dist_obf/manager_activation.py" "license/client/manager_activation.py"

# Copy PyArmor runtime (dynamic name detection)
PYARMOR_RUNTIME=$(ls -d dist_obf/pyarmor_runtime_* 2>/dev/null | head -1 | xargs basename)
if [ -z "$PYARMOR_RUNTIME" ]; then
    echo "ERROR: No PyArmor runtime found in dist_obf!"
    exit 1
fi
echo "Found PyArmor runtime: $PYARMOR_RUNTIME"
mkdir -p "license/$PYARMOR_RUNTIME"
cp -r "dist_obf/$PYARMOR_RUNTIME/"* "license/$PYARMOR_RUNTIME/"

# Clean previous builds
echo ""
echo "[5/7] Cleaning previous builds..."
rm -rf packaging/linux/dist
rm -rf packaging/linux/build_temp
mkdir -p packaging/linux/dist

# Check if spec file exists
SPEC_FILE="packaging/linux/specs/botifytrades.spec"
if [ ! -f "$SPEC_FILE" ]; then
    echo "ERROR: Spec file not found at $SPEC_FILE"
    exit 1
fi

# Build with PyInstaller using the spec file
echo ""
echo "[6/7] Building executable with PyInstaller..."

pyinstaller --clean \
    --noconfirm \
    --distpath "packaging/linux/dist" \
    --workpath "packaging/linux/build_temp" \
    "$SPEC_FILE"

if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: PyInstaller build failed!"
    exit 1
fi

# Compress with UPX (optional)
echo ""
echo "[7/7] Compressing executable with UPX..."
if command -v upx &> /dev/null; then
    upx --best "packaging/linux/dist/BotifyTrades" 2>/dev/null || echo "UPX compression skipped (may not be applicable)"
else
    echo "UPX not found - skipping compression (optional)"
fi

# Create distribution package
mkdir -p packaging/linux/dist/config

# Copy example config if it exists
if [ -f "config.ini.example" ]; then
    cp "config.ini.example" "packaging/linux/dist/config.ini.example"
fi

# Copy HTML helpers if they exist
[ -f "GET_DISCORD_TOKEN.html" ] && cp "GET_DISCORD_TOKEN.html" "packaging/linux/dist/"
[ -f "GET_WEBULL_TOKENS.html" ] && cp "GET_WEBULL_TOKENS.html" "packaging/linux/dist/"

# Create run script
cat > packaging/linux/dist/run.sh << 'EOF'
#!/bin/bash
echo "Starting BotifyTrades..."
./BotifyTrades
EOF
chmod +x packaging/linux/dist/run.sh
chmod +x packaging/linux/dist/BotifyTrades

# Create README
cat > packaging/linux/dist/README.txt << 'EOF'
BotifyTrades - Discord Trading Bot
===================================

QUICK START:
1. Run ./run.sh or ./BotifyTrades
2. Open http://localhost:5000 in your browser
3. Complete the setup wizard

FIRST TIME SETUP:
- Create admin account via setup wizard
- Enter your license key
- Configure broker connections (Discord, Alpaca, Webull, IBKR)

LICENSE:
- Obtain a license key from support
- Enter it in the License Management page
- License binds to this machine on first activation

SUPPORT:
- For issues, contact support with your Machine ID
- Machine ID can be found in the License Management page

BUILD INFO:
- This build is protected with PyArmor obfuscation

EOF

echo ""
echo "========================================================================"
echo "  BUILD COMPLETE!"
echo "========================================================================"
echo "  Location: packaging/linux/dist/"
echo "  Executable: BotifyTrades"
echo "  Protection: PyArmor + PyInstaller + UPX"
echo ""
echo "  To run: cd packaging/linux/dist && ./run.sh"
echo "========================================================================"
echo ""
