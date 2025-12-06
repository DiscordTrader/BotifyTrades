#!/bin/bash
# Quick start script for Mac/Linux

echo "╔════════════════════════════════════════════════════════════╗"
echo "║        Ψ∿ QuantumPulse - Local Launcher                   ║"
echo "║          Professional Discord Trading Bot                  ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed!"
    echo "Please install Python 3.11+ from https://www.python.org/downloads/"
    exit 1
fi

echo "✓ Python found: $(python3 --version)"
echo ""

# Check if environment variables are set
if [ -z "$DISCORD_USER_TOKEN" ]; then
    echo "⚠️  WARNING: DISCORD_USER_TOKEN not set!"
    echo "Set it with: export DISCORD_USER_TOKEN='your_token'"
    echo ""
fi

if [ -z "$WEBULL_ACCESS_TOKEN" ]; then
    echo "⚠️  WARNING: WEBULL_ACCESS_TOKEN not set!"
    echo ""
fi

if [ -z "$WEBULL_TRADE_PIN" ]; then
    echo "⚠️  WARNING: WEBULL_TRADE_PIN not set!"
    echo ""
fi

# Check if dependencies are installed
echo "Checking dependencies..."
if ! python3 -c "import discord" 2>/dev/null; then
    echo "Installing dependencies..."
    if ! python3 -m pip install -r requirements.txt; then
        echo "❌ ERROR: Failed to install dependencies"
        echo "Try running: python3 -m pip install --upgrade pip"
        exit 1
    fi
fi

echo ""
echo "Starting bot..."
echo "Press Ctrl+C to stop"
echo ""

# Run the bot
python3 src/selfbot_webull.py
