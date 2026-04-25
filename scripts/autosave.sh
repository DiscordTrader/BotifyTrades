#!/usr/bin/env bash
# =============================================================================
# BotifyTradesv2 Auto-Save Script
# Called by Claude Code hooks (PostToolUse + Stop) and Windows Task Scheduler.
# =============================================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCKFILE="$REPO_DIR/.git/autosave.lock"
HEARTBEAT_FILE="$REPO_DIR/.autosave_heartbeat"
PUSH_LOG="$REPO_DIR/.autosave_push.log"
DEBOUNCE_SECONDS=30

# Allow forced save (bypasses debounce, used by Stop hook)
if [ "${FORCE_SAVE:-0}" = "1" ]; then
    DEBOUNCE_SECONDS=0
fi

# --- Guard: skip if another git operation is in progress ---
if [ -f "$REPO_DIR/.git/index.lock" ]; then
    exit 0
fi

# --- Guard: skip if in rebase, merge, or cherry-pick ---
if [ -d "$REPO_DIR/.git/rebase-merge" ] || [ -d "$REPO_DIR/.git/rebase-apply" ] || [ -f "$REPO_DIR/.git/MERGE_HEAD" ]; then
    exit 0
fi

# --- Guard: skip if on main or master ---
branch=$(cd "$REPO_DIR" && git branch --show-current 2>/dev/null || echo "")
if [ -z "$branch" ] || [ "$branch" = "main" ] || [ "$branch" = "master" ]; then
    exit 0
fi

# --- Mutex: prevent concurrent runs (mkdir is atomic on all platforms) ---
MUTEX_DIR="$REPO_DIR/.git/autosave_mutex"
if ! mkdir "$MUTEX_DIR" 2>/dev/null; then
    # Another instance is running — check if it's stale (>120s old)
    if [ -f "$MUTEX_DIR/pid" ]; then
        mutex_age=$(( $(date +%s) - $(stat -c %Y "$MUTEX_DIR/pid" 2>/dev/null || echo 0) ))
        if [ "$mutex_age" -gt 120 ]; then
            rm -rf "$MUTEX_DIR"
            mkdir "$MUTEX_DIR" 2>/dev/null || exit 0
        else
            exit 0
        fi
    else
        exit 0
    fi
fi
echo $$ > "$MUTEX_DIR/pid"
trap 'rm -rf "$MUTEX_DIR"' EXIT

# --- Debounce: skip if last auto-save was too recent ---
if [ -f "$HEARTBEAT_FILE" ]; then
    last_save=$(cat "$HEARTBEAT_FILE" 2>/dev/null || echo 0)
    now=$(date +%s)
    elapsed=$((now - last_save))
    if [ "$elapsed" -lt "$DEBOUNCE_SECONDS" ]; then
        exit 0
    fi
fi

cd "$REPO_DIR"

# --- Stage only source/config files in safe directories ---
SAFE_DIRS="src/ gui_app/ scripts/ tests/ ui/ upgrade/ docs/ .github/ qa/"
SAFE_EXT_PATTERN='\.(py|js|jsx|ts|tsx|html|css|sh|bat|md|txt|yml|yaml|ini|toml|cfg|nix|spec|svg)$'

# Modified tracked files in safe directories only
changed_files=""
for dir in $SAFE_DIRS; do
    if [ -d "$dir" ]; then
        dir_changes=$(git diff --name-only -- "$dir" 2>/dev/null | grep -E "$SAFE_EXT_PATTERN" || true)
        if [ -n "$dir_changes" ]; then
            changed_files=$(printf '%s\n%s' "$changed_files" "$dir_changes")
        fi
    fi
done

# Untracked source files in safe directories only
untracked_files=""
for dir in $SAFE_DIRS; do
    if [ -d "$dir" ]; then
        dir_untracked=$(git ls-files --others --exclude-standard -- "$dir" 2>/dev/null | grep -E "$SAFE_EXT_PATTERN" || true)
        if [ -n "$dir_untracked" ]; then
            untracked_files=$(printf '%s\n%s' "$untracked_files" "$dir_untracked")
        fi
    fi
done

# Safe root config files (explicit allowlist)
root_config=$(git diff --name-only 2>/dev/null | grep -E '^(\.gitignore|CLAUDE\.md|README\.md|requirements\.txt|Makefile|pytest\.ini)$' || true)

# .claude/settings.json
claude_config=$(git diff --name-only -- .claude/settings.json 2>/dev/null || true)
claude_new=$(git ls-files --others --exclude-standard -- .claude/settings.json 2>/dev/null || true)

# Combine all files
all_files=$(printf '%s\n%s\n%s\n%s\n%s' "$changed_files" "$untracked_files" "$root_config" "$claude_config" "$claude_new" | sort -u | grep -v '^$' || true)

if [ -z "$all_files" ]; then
    exit 0
fi

# --- Validate Python syntax before committing ---
py_files=$(echo "$all_files" | grep '\.py$' || true)
if [ -n "$py_files" ]; then
    syntax_errors=""
    while IFS= read -r pyfile; do
        [ -z "$pyfile" ] && continue
        if ! python -m py_compile "$pyfile" 2>/dev/null; then
            syntax_errors="$syntax_errors\n  $pyfile"
        fi
    done <<< "$py_files"

    if [ -n "$syntax_errors" ]; then
        echo "[auto-save] BLOCKED: Python syntax errors found in:" >&2
        echo -e "$syntax_errors" >&2
        exit 0
    fi
fi

# --- Stage the files ---
echo "$all_files" | xargs git add -- 2>/dev/null

# --- Verify something is actually staged ---
if git diff --cached --quiet 2>/dev/null; then
    exit 0
fi

# --- Detect area from changed files for semantic commit message ---
area=""
if echo "$all_files" | grep -q '^src/risk/'; then
    area="[risk]"
elif echo "$all_files" | grep -q '^src/brokers/'; then
    area="[broker]"
elif echo "$all_files" | grep -q '^src/services/'; then
    area="[services]"
elif echo "$all_files" | grep -q '^gui_app/'; then
    area="[ui]"
elif echo "$all_files" | grep -q '^scripts/'; then
    area="[scripts]"
elif echo "$all_files" | grep -q '^docs/'; then
    area="[docs]"
fi

# --- Build commit message ---
timestamp=$(date '+%Y-%m-%d %H:%M')
file_count=$(echo "$all_files" | wc -l | tr -d ' ')
file_list=$(echo "$all_files" | head -10 | tr '\n' ', ' | sed 's/,$//')

git commit -m "$(cat <<CMTEOF
[auto-save]${area} ${branch} | ${timestamp} | ${file_count} file(s)

Files: ${file_list}

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
CMTEOF
)"

# --- Write heartbeat ---
date +%s > "$HEARTBEAT_FILE"

# --- Create daily backup tag (once per day) ---
today=$(date '+%Y-%m-%d')
backup_tag="backup/${branch}/${today}"
if ! git tag -l "$backup_tag" | grep -q .; then
    git tag "$backup_tag" HEAD 2>/dev/null || true
fi

# --- Push to remote (synchronous, with timeout, no credential prompt) ---
export GIT_TERMINAL_PROMPT=0
if timeout 30 git push origin "$branch" 2>>"$PUSH_LOG"; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Push OK" >> "$PUSH_LOG"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Push FAILED (exit $?)" >> "$PUSH_LOG"
fi

exit 0
