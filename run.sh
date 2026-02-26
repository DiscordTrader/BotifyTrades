#!/bin/bash
# Quick start script for Mac/Linux - with auto-restart on crash

echo "╔════════════════════════════════════════════════════════════╗"
echo "║              BotifyTrades - Local Launcher                 ║"
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
echo "Starting bot with auto-restart enabled..."
echo "The bot will automatically restart if it crashes unexpectedly."
echo "Press Ctrl+C to fully stop the bot."
echo ""

while true; do
    echo "[$(date '+%H:%M:%S')] Starting BotifyTrades..."
    python3 src/selfbot_webull.py
    EXIT_CODE=$?

    # Exit code 0 = clean shutdown (Ctrl+C), do not restart
    if [ $EXIT_CODE -eq 0 ]; then
        echo ""
        echo "Bot stopped cleanly."
        break
    fi

    # Any non-zero exit code = crash, auto-restart after delay
    echo ""
    echo "[$(date '+%H:%M:%S')] Bot stopped unexpectedly (exit code $EXIT_CODE). Restarting in 5 seconds..."
    echo "Press Ctrl+C now to cancel restart."
    sleep 5
done
