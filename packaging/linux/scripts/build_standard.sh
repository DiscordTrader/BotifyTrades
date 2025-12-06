#!/bin/bash
# ========================================================================
#   BotifyTrades - Linux Standard Build
#   Protection Level: Standard (PyInstaller packaging + UPX compression)
#   Uses consolidated license/ module
#   Note: --key encryption was removed in PyInstaller v6.0 (2023)
# ========================================================================

echo ""
echo "========================================================================"
echo "  BotifyTrades Trading Bot - Linux Standard Build"
echo "  Protection: PyInstaller + UPX Compression"
echo "========================================================================"
echo ""

# Navigate to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$PROJECT_ROOT"

echo "Project root: $PROJECT_ROOT"

# Check dependencies
echo "[1/5] Checking dependencies..."
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 not found. Please install Python 3.8+"
    exit 1
fi

echo "Python version: $(python3 --version)"

if ! pip show pyinstaller &> /dev/null; then
    echo "Installing PyInstaller..."
    pip install pyinstaller
fi

# Clean previous builds
echo ""
echo "[2/5] Cleaning previous builds..."
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
echo "[3/5] Building executable with PyInstaller..."

pyinstaller --clean \
    --noconfirm \
    --distpath "packaging/linux/dist" \
    --workpath "packaging/linux/build_temp" \
    "$SPEC_FILE"

if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: Build failed!"
    exit 1
fi

# Compress with UPX (optional)
echo ""
echo "[4/5] Compressing executable with UPX..."
if command -v upx &> /dev/null; then
    upx --best "packaging/linux/dist/BotifyTrades" 2>/dev/null || echo "UPX compression skipped (may not be applicable)"
else
    echo "UPX not found - skipping compression (optional)"
fi

# Create distribution package
echo ""
echo "[5/5] Creating distribution package..."
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

EOF

# Clean up temp files
echo ""
echo "Cleaning up temporary files..."
rm -rf packaging/linux/build_temp

echo ""
echo "========================================================================"
echo "  BUILD COMPLETE!"
echo "========================================================================"
echo "  Location: packaging/linux/dist/"
echo "  Executable: BotifyTrades"
echo "  Protection Level: STANDARD (PyInstaller + UPX)"
echo ""
echo "  To run: cd packaging/linux/dist && ./run.sh"
echo "========================================================================"
echo ""
