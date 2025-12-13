#!/bin/bash
# BotifyTrades Release Script
# Usage: ./scripts/release.sh [version]
# Example: ./scripts/release.sh 3.2.1

set -e

VERSION=${1:-}

if [ -z "$VERSION" ]; then
    echo "Usage: ./scripts/release.sh <version>"
    echo "Example: ./scripts/release.sh 3.2.1"
    exit 1
fi

echo "============================================"
echo "BotifyTrades Release Script v$VERSION"
echo "============================================"

# Update version.py
echo "[1/4] Updating version.py..."
sed -i "s/APP_VERSION = \"[^\"]*\"/APP_VERSION = \"$VERSION\"/" upgrade/version.py
sed -i "s/BUILD_DATE = \"[^\"]*\"/BUILD_DATE = \"$(date +%Y-%m-%d)\"/" upgrade/version.py
echo "       APP_VERSION = \"$VERSION\""
echo "       BUILD_DATE = \"$(date +%Y-%m-%d)\""

# Stage all changes
echo "[2/4] Staging changes..."
git add -A

# Commit
echo "[3/4] Committing..."
git commit -m "Release v$VERSION" || echo "Nothing to commit"

# Push
echo "[4/4] Pushing to origin..."
git push origin main

echo ""
echo "============================================"
echo "✓ Release v$VERSION pushed successfully!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Go to GitHub: https://github.com/DiscordTrader/BotifyTradesv2"
echo "  2. Create a new Release with tag: v$VERSION"
echo "  3. This will trigger the build workflow on the public repo"
echo ""
