#!/bin/bash
# ========================================================================
#   BotifyTrades - macOS Build with PyArmor Obfuscation
#   Protection: PyArmor + PyInstaller
#   Note: NO GIT REQUIRED - version is read from upgrade/version.py
# ========================================================================

set -e

echo ""
echo "========================================================================"
echo "  BotifyTrades Trading Bot - macOS Protected Build"
echo "  Protection: PyArmor Obfuscation + PyInstaller"
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
    echo "  brew install python3"
    exit 1
fi

echo "Python version: $(python3 --version)"

# Check Python architecture
PYTHON_ARCH=$(python3 -c "import platform; print(platform.machine())")
echo "Python architecture: $PYTHON_ARCH"
echo ""
echo "NOTE: Building for native architecture ($PYTHON_ARCH)"
echo "  - Intel Mac (x86_64): Creates Intel-only binary"
echo "  - Apple Silicon (arm64): Creates Apple Silicon-only binary"
echo "  - For cross-platform distribution, build on BOTH architectures"
echo ""

if ! pip3 show pyarmor &> /dev/null; then
    echo "Installing PyArmor..."
    pip3 install pyarmor
fi

if ! pip3 show pyinstaller &> /dev/null; then
    echo "Installing PyInstaller..."
    pip3 install pyinstaller
fi

# Install required dependencies
echo "Checking required packages..."
pip3 install -q discord.py-self webull flask cryptography requests openai aiohttp yfinance pandas numpy ta alpaca-py certifi 2>/dev/null || true

# Backup original files
echo ""
echo "[2/7] Backing up original license files..."
mkdir -p packaging/macos/backup
cp "license/config/constants.py" "packaging/macos/backup/constants.py.bak"
cp "license/client/manager_secure.py" "packaging/macos/backup/manager_secure.py.bak"
cp "license/client/manager_activation.py" "packaging/macos/backup/manager_activation.py.bak"

# Function to restore files on error or completion
restore_files() {
    echo ""
    echo "Restoring original license files..."
    cp -f "packaging/macos/backup/constants.py.bak" "license/config/constants.py"
    cp -f "packaging/macos/backup/manager_secure.py.bak" "license/client/manager_secure.py"
    cp -f "packaging/macos/backup/manager_activation.py.bak" "license/client/manager_activation.py"
    
    # Clean up
    echo "Cleaning up temporary files..."
    rm -rf dist_obf
    rm -rf packaging/macos/build_temp
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
rm -rf packaging/macos/dist
rm -rf packaging/macos/build_temp
mkdir -p packaging/macos/dist

# Check if spec file exists
SPEC_FILE="packaging/macos/specs/botifytrades.spec"
if [ ! -f "$SPEC_FILE" ]; then
    echo "ERROR: Spec file not found at $SPEC_FILE"
    exit 1
fi

# Build with PyInstaller using the spec file
echo ""
echo "[6/7] Building executable with PyInstaller..."

python3 -m PyInstaller --clean \
    --noconfirm \
    --distpath "packaging/macos/dist" \
    --workpath "packaging/macos/build_temp" \
    "$SPEC_FILE"

if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: PyInstaller build failed!"
    exit 1
fi

# Create distribution package
echo ""
echo "[7/7] Creating distribution package..."
mkdir -p packaging/macos/dist/config

# Copy example config if it exists
if [ -f "config.ini.example" ]; then
    cp "config.ini.example" "packaging/macos/dist/config.ini.example"
fi

# Copy HTML helpers if they exist
[ -f "GET_DISCORD_TOKEN.html" ] && cp "GET_DISCORD_TOKEN.html" "packaging/macos/dist/"
[ -f "GET_WEBULL_TOKENS.html" ] && cp "GET_WEBULL_TOKENS.html" "packaging/macos/dist/"

# Create run script
cat > packaging/macos/dist/run.command << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
echo "Starting BotifyTrades..."
./BotifyTrades
EOF
chmod +x packaging/macos/dist/run.command
chmod +x packaging/macos/dist/BotifyTrades

# Create README
cat > packaging/macos/dist/README.txt << 'EOF'
BotifyTrades - Discord Trading Bot
===================================

QUICK START:
1. Double-click run.command or run ./BotifyTrades in Terminal
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

MACOS SECURITY NOTE:
- If blocked by Gatekeeper, right-click and select "Open"
- Or run: xattr -cr ./BotifyTrades

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
echo "  Location: packaging/macos/dist/"
echo "  Executable: BotifyTrades"
echo "  Protection: PyArmor + PyInstaller"
echo ""

# Verify architecture of built binary
echo "  Verifying binary architecture..."
if [ -f "packaging/macos/dist/BotifyTrades" ]; then
    BINARY_ARCH=$(file packaging/macos/dist/BotifyTrades)
    echo "  $BINARY_ARCH"
    if echo "$BINARY_ARCH" | grep -q "universal"; then
        echo "  ✓ Universal binary - works on Intel AND Apple Silicon"
    elif echo "$BINARY_ARCH" | grep -q "arm64"; then
        echo "  ⚠ ARM64 only - works on Apple Silicon (M1/M2/M3) only"
        echo "  ⚠ Intel Mac users will see 'Bad CPU type' error"
    elif echo "$BINARY_ARCH" | grep -q "x86_64"; then
        echo "  ⚠ x86_64 only - works on Intel Macs only"
        echo "  ⚠ Apple Silicon users need Rosetta 2"
    fi
fi
echo ""
echo "  To run: cd packaging/macos/dist && ./run.command"
echo "========================================================================"
echo ""
