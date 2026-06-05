#!/bin/bash
# Linux/Mac build script for Discord Trading Bot
# This script builds the bot into a standalone executable

echo "============================================================"
echo "Discord Trading Bot - Build Script"
echo "============================================================"
echo ""

# Check if PyInstaller is installed
if ! python3 -c "import PyInstaller" 2>/dev/null; then
    echo "[ERROR] PyInstaller not found! Installing..."
    pip3 install pyinstaller
    echo ""
fi

echo "[BUILD] Starting build process..."
echo ""

# Clean previous builds
echo "[BUILD] Cleaning previous builds..."
rm -rf build dist
echo ""

# Build the executable
echo "[BUILD] Building executable with PyInstaller..."
pyinstaller build_exe.spec --clean --noconfirm
echo ""

# Check if build succeeded
if [ ! -f "dist/DiscordTradingBot" ]; then
    echo "[ERROR] Build failed! Check errors above."
    exit 1
fi

# Make executable
chmod +x dist/DiscordTradingBot

echo "============================================================"
echo "[SUCCESS] Build completed successfully!"
echo "============================================================"
echo ""
echo "Distributable package location: dist/"
echo ""
echo "Package contents:"
echo "  - DiscordTradingBot  (Main executable)"
echo "  - config.ini         (Configuration file)"
echo ""
echo "Next steps:"
echo "  1. Test the executable: cd dist && ./DiscordTradingBot"
echo "  2. Generate license keys for customers"
echo "  3. Distribute the executable + config.ini + license key"
echo ""
echo "============================================================"
