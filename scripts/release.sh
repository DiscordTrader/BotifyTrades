#!/bin/bash
# =============================================================================
# BotifyTrades Release Script
# =============================================================================
# Usage: ./scripts/release.sh <version>
# Example: ./scripts/release.sh 3.2.1
#
# This script:
# 1. Updates upgrade/version.py with the new version
# 2. Commits and pushes to BotifyTradesv2 (private)
# 3. Triggers the build workflow on BotifyTrades (public) via GitHub API
#
# Requirements:
# - RELEASE_TOKEN environment variable (GitHub PAT with 'repo' scope)
# =============================================================================

set -e

VERSION=${1:-}
PUBLIC_REPO="DiscordTrader/BotifyTrades"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_step() {
    echo -e "${BLUE}[$1/$2]${NC} $3"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

# Validate input
if [ -z "$VERSION" ]; then
    echo ""
    echo "BotifyTrades Release Script"
    echo "==========================="
    echo ""
    echo "Usage: ./scripts/release.sh <version>"
    echo ""
    echo "Examples:"
    echo "  ./scripts/release.sh 3.2.1"
    echo "  ./scripts/release.sh 3.3.0"
    echo ""
    exit 1
fi

# Validate version format
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    print_error "Invalid version format: $VERSION"
    echo "Version must be in format: X.Y.Z (e.g., 3.2.1)"
    exit 1
fi

echo ""
echo "============================================"
echo "  BotifyTrades Release v$VERSION"
echo "============================================"
echo ""

# Step 1: Update version.py
print_step 1 5 "Updating upgrade/version.py..."
BUILD_DATE=$(date +%Y-%m-%d)
sed -i "s/APP_VERSION = \"[^\"]*\"/APP_VERSION = \"$VERSION\"/" upgrade/version.py
sed -i "s/BUILD_DATE = \"[^\"]*\"/BUILD_DATE = \"$BUILD_DATE\"/" upgrade/version.py
print_success "APP_VERSION = \"$VERSION\""
print_success "BUILD_DATE = \"$BUILD_DATE\""

# Step 2: Stage changes
print_step 2 5 "Staging changes..."
git add -A
print_success "All changes staged"

# Step 3: Commit
print_step 3 5 "Committing..."
git commit -m "Release v$VERSION" 2>/dev/null || {
    print_warning "Nothing to commit (version may already be set)"
}
print_success "Committed"

# Step 4: Push to private repo
print_step 4 5 "Pushing to origin..."
git push origin main
print_success "Pushed to BotifyTradesv2 (private)"

# Step 5: Trigger build workflow on public repo
print_step 5 5 "Triggering build workflow..."

if [ -z "$RELEASE_TOKEN" ]; then
    print_warning "RELEASE_TOKEN not set - skipping automatic build trigger"
    echo ""
    echo "To trigger the build manually:"
    echo "  1. Go to: https://github.com/$PUBLIC_REPO/actions"
    echo "  2. Select 'Build and Release' workflow"
    echo "  3. Click 'Run workflow'"
    echo "  4. Enter version: $VERSION"
    echo ""
else
    # Trigger repository_dispatch event
    RESPONSE=$(curl -s -X POST \
        -H "Accept: application/vnd.github+json" \
        -H "Authorization: Bearer $RELEASE_TOKEN" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        "https://api.github.com/repos/$PUBLIC_REPO/dispatches" \
        -d "{\"event_type\":\"release_ready\",\"client_payload\":{\"version\":\"$VERSION\"}}" \
        -w "%{http_code}" \
        -o /dev/null)
    
    if [ "$RESPONSE" == "204" ]; then
        print_success "Build workflow triggered on $PUBLIC_REPO"
    else
        print_warning "Failed to trigger workflow (HTTP $RESPONSE)"
        echo "You may need to trigger manually at:"
        echo "  https://github.com/$PUBLIC_REPO/actions"
    fi
fi

echo ""
echo "============================================"
echo -e "  ${GREEN}✓ Release v$VERSION Complete!${NC}"
echo "============================================"
echo ""
echo "Next steps:"
echo "  • Check build status: https://github.com/$PUBLIC_REPO/actions"
echo "  • View release: https://github.com/$PUBLIC_REPO/releases"
echo ""
