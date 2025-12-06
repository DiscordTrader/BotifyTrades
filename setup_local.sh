#!/bin/bash

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║         Ψ∿ QuantumPulse - Automatic Local Setup              ║"
echo "║              Professional Discord Trading Bot                  ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Check Python installation
echo "[1/5] Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo "❌ ERROR: Python 3 not found!"
    echo ""
    echo "Please install Python 3.11+ using your package manager:"
    echo "  macOS: brew install python@3.11"
    echo "  Ubuntu/Debian: sudo apt install python3.11"
    exit 1
fi
echo "✅ Python 3 found"

# Check Python version
echo "[2/5] Verifying Python version..."
PYVER=$(python3 --version | cut -d' ' -f2)
echo "   Python version: $PYVER"
echo "✅ Version check passed"

# Install dependencies
echo "[3/5] Installing dependencies (this may take 2-3 minutes)..."
if ! pip3 install -r requirements.txt; then
    echo "❌ ERROR: Failed to install dependencies"
    exit 1
fi
echo "✅ Dependencies installed"

# Create config file if doesn't exist
echo "[4/5] Setting up configuration..."
if [ ! -f "config.ini" ]; then
    if [ -f "config.ini.example" ]; then
        cp config.ini.example config.ini
        echo "✅ Created config.ini from template"
        echo ""
        echo "⚠️  IMPORTANT: You must edit config.ini with your credentials!"
        echo "   - Discord token"
        echo "   - Webull credentials"
        echo "   - API keys"
        echo "   - License key"
    else
        echo "❌ WARNING: config.ini.example not found"
    fi
else
    echo "✅ config.ini already exists"
fi

echo ""
echo "[5/5] Setup complete! 🎉"
echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                     NEXT STEPS                                 ║"
echo "╠════════════════════════════════════════════════════════════════╣"
echo "║ 1. Edit config.ini with your credentials                      ║"
echo "║    - Use GET_DISCORD_TOKEN.html for Discord token             ║"
echo "║    - Use GET_WEBULL_TOKENS.html for Webull credentials        ║"
echo "║                                                                ║"
echo "║ 2. Run the bot:                                                ║"
echo "║    python3 src/selfbot_webull.py                               ║"
echo "║                                                                ║"
echo "║ 3. Open web GUI in browser:                                    ║"
echo "║    http://127.0.0.1:5000                                       ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
