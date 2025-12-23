#!/bin/bash
# =============================================================================
# BotifyTrades Release Script
# =============================================================================
# Usage: ./scripts/release.sh <build_type> <version>
# Example: ./scripts/release.sh admin 3.2.1
#          ./scripts/release.sh user 3.2.1
#
# This script:
# 1. Sets BUILD_TYPE in the codebase (ADMIN or USER)
# 2. Updates upgrade/version.py with the new version
# 3. Commits and pushes to BotifyTradesv2 (private)
# 4. Triggers the build workflow on BotifyTrades (public) via GitHub API
#
# Requirements:
# - RELEASE_TOKEN environment variable (GitHub PAT with 'repo' scope)
# =============================================================================

set -e

BUILD_TYPE_ARG=${1:-}
VERSION=${2:-}
PUBLIC_REPO="DiscordTrader/BotifyTrades"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
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
if [ -z "$BUILD_TYPE_ARG" ] || [ -z "$VERSION" ]; then
    echo ""
    echo "BotifyTrades Release Script"
    echo "==========================="
    echo ""
    echo "Usage: ./scripts/release.sh <build_type> <version>"
    echo ""
    echo "Build Types:"
    echo "  admin  - Full features (Channel Mappings, all admin tools)"
    echo "  user   - Limited features (admin-only features hidden)"
    echo ""
    echo "Examples:"
    echo "  ./scripts/release.sh admin 3.2.1    # Admin build with all features"
    echo "  ./scripts/release.sh user 3.2.1     # User build with limited features"
    echo ""
    exit 1
fi

# Normalize build type to uppercase
BUILD_TYPE_UPPER=$(echo "$BUILD_TYPE_ARG" | tr '[:lower:]' '[:upper:]')

# Validate build type
if [ "$BUILD_TYPE_UPPER" != "ADMIN" ] && [ "$BUILD_TYPE_UPPER" != "USER" ]; then
    print_error "Invalid build type: $BUILD_TYPE_ARG"
    echo "Build type must be 'admin' or 'user'"
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
echo -e "  Build Type: ${CYAN}$BUILD_TYPE_UPPER${NC}"
echo "============================================"
echo ""

# Step 1: Set BUILD_TYPE in selfbot_webull.py
print_step 1 6 "Setting BUILD_TYPE to $BUILD_TYPE_UPPER..."

# Update the BUILD_TYPE line in selfbot_webull.py
sed -i "s/^BUILD_TYPE = .*/BUILD_TYPE = '$BUILD_TYPE_UPPER'  # Set by release.sh/" src/selfbot_webull.py

print_success "BUILD_TYPE = '$BUILD_TYPE_UPPER'"

# Step 2: Update version.py
print_step 2 6 "Updating upgrade/version.py..."
BUILD_DATE=$(date +%Y-%m-%d)
sed -i "s/APP_VERSION = \"[^\"]*\"/APP_VERSION = \"$VERSION\"/" upgrade/version.py
sed -i "s/BUILD_DATE = \"[^\"]*\"/BUILD_DATE = \"$BUILD_DATE\"/" upgrade/version.py
print_success "APP_VERSION = \"$VERSION\""
print_success "BUILD_DATE = \"$BUILD_DATE\""

# Step 3: Stage changes
print_step 3 6 "Staging changes..."
git add -A
print_success "All changes staged"

# Step 4: Commit
print_step 4 6 "Committing..."
COMMIT_MSG="Release v$VERSION ($BUILD_TYPE_UPPER build)"
git commit -m "$COMMIT_MSG" 2>/dev/null || {
    print_warning "Nothing to commit (version/build type may already be set)"
}
print_success "Committed: $COMMIT_MSG"

# Step 5: Push to private repo
print_step 5 6 "Pushing to origin..."
git push origin main
print_success "Pushed to BotifyTradesv2 (private)"

# Step 6: Trigger build workflow on public repo
print_step 6 6 "Triggering build workflow..."

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
    # Trigger repository_dispatch event with build type
    RESPONSE=$(curl -s -X POST \
        -H "Accept: application/vnd.github+json" \
        -H "Authorization: Bearer $RELEASE_TOKEN" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        "https://api.github.com/repos/$PUBLIC_REPO/dispatches" \
        -d "{\"event_type\":\"release_ready\",\"client_payload\":{\"version\":\"$VERSION\",\"build_type\":\"$BUILD_TYPE_UPPER\"}}" \
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
echo -e "  ${GREEN}✓ Release v$VERSION ($BUILD_TYPE_UPPER) Complete!${NC}"
echo "============================================"
echo ""

if [ "$BUILD_TYPE_UPPER" == "USER" ]; then
    echo -e "${YELLOW}Note: This is a USER build - admin features are hidden${NC}"
    echo ""
fi

echo "Next steps:"
echo "  • Check build status: https://github.com/$PUBLIC_REPO/actions"
echo "  • View release: https://github.com/$PUBLIC_REPO/releases"
echo ""
