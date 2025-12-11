#!/bin/bash
# ========================================================================
#   BotifyTrades - macOS Standard Build
#   Protection Level: Standard (PyInstaller packaging)
#   Uses consolidated license/ module
#   Produces: BotifyTrades.app (macOS Application Bundle)
#   Note: NO GIT REQUIRED - version is read from upgrade/version.py
# ========================================================================

set -e

echo ""
echo "========================================================================"
echo "  BotifyTrades Trading Bot - macOS Standard Build"
echo "  Protection: PyInstaller packaging"
echo "========================================================================"
echo ""

# Navigate to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$PROJECT_ROOT"

# Check dependencies
echo "[1/5] Checking dependencies..."

if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python3 not found. Please install Python 3.8+"
    echo "  brew install python3"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
echo "  Python version: $PYTHON_VERSION"

if ! python3 -c "import pyinstaller" &> /dev/null; then
    echo "  Installing PyInstaller..."
    pip3 install pyinstaller
fi

# Install required dependencies
echo "  Checking required packages..."
pip3 install -q discord.py-self webull flask cryptography requests openai aiohttp yfinance pandas numpy ta alpaca-py 2>/dev/null || true

# Clean previous builds
echo ""
echo "[2/5] Cleaning previous builds..."
rm -rf "packaging/macos/dist"
rm -rf "packaging/macos/build_temp"
mkdir -p "packaging/macos/dist"

# Build with PyInstaller
echo ""
echo "[3/5] Building macOS application with PyInstaller..."

python3 -m PyInstaller --clean --noconfirm \
    --distpath "packaging/macos/dist" \
    --workpath "packaging/macos/build_temp" \
    packaging/macos/specs/botifytrades.spec

if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: Build failed!"
    exit 1
fi

# Create distribution package
echo ""
echo "[4/5] Creating distribution package..."

# Copy support files
mkdir -p "packaging/macos/dist/BotifyTrades"
if [ -f "config.ini.example" ]; then
    cp "config.ini.example" "packaging/macos/dist/BotifyTrades/"
fi
if [ -f "GET_DISCORD_TOKEN.html" ]; then
    cp "GET_DISCORD_TOKEN.html" "packaging/macos/dist/BotifyTrades/"
fi
if [ -f "GET_WEBULL_TOKENS.html" ]; then
    cp "GET_WEBULL_TOKENS.html" "packaging/macos/dist/BotifyTrades/"
fi

# Create launcher script
cat > "packaging/macos/dist/BotifyTrades/run.command" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
echo "Starting BotifyTrades..."
./BotifyTrades
EOF
chmod +x "packaging/macos/dist/BotifyTrades/run.command"

# Create README
cat > "packaging/macos/dist/BotifyTrades/README.txt" << 'EOF'
BotifyTrades - Discord Trading Bot
===================================

QUICK START (macOS):
1. Double-click run.command OR open Terminal and run ./BotifyTrades
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
If macOS blocks the app, go to:
  System Preferences > Security & Privacy > General
  Click "Open Anyway" next to the BotifyTrades message

SUPPORT:
- For issues, contact support with your Machine ID
- Machine ID can be found in the License Management page
EOF

# Clean up temp files
echo ""
echo "[5/5] Cleaning up temporary files..."
rm -rf "packaging/macos/build_temp"

echo ""
echo "========================================================================"
echo "  BUILD COMPLETE!"
echo "========================================================================"
echo "  Location: packaging/macos/dist/BotifyTrades/"
echo "  Executable: BotifyTrades"
echo "  Launcher: run.command (double-click to start)"
echo "========================================================================"
echo ""
echo "To run the application:"
echo "  cd packaging/macos/dist/BotifyTrades"
echo "  ./BotifyTrades"
echo ""
