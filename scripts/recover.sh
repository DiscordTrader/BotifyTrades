#!/usr/bin/env bash
# =============================================================================
# BotifyTradesv2 Recovery Tool
# Usage: bash scripts/recover.sh <command> [args]
# =============================================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

HEARTBEAT_FILE="$REPO_DIR/.autosave_heartbeat"
PUSH_LOG="$REPO_DIR/.autosave_push.log"

usage() {
    echo "BotifyTradesv2 Recovery Tool"
    echo ""
    echo "Usage: bash scripts/recover.sh <command> [args]"
    echo ""
    echo "Commands:"
    echo "  list [today|tags]    List recovery points (auto-saves, tags)"
    echo "  show <commit>        Show what changed in a specific commit"
    echo "  file <commit> <path> Restore a single file from a commit"
    echo "  undo <N>             Revert last N auto-save commits"
    echo "  snapshot             Create a manual backup tag right now"
    echo "  status               Show auto-save health"
    echo "  diff <commit>        Show full diff for a commit"
    echo ""
    exit 1
}

cmd_list() {
    local filter="${1:-all}"
    case "$filter" in
        today)
            echo "=== Today's Auto-Save Commits ==="
            git log --oneline --since="$(date '+%Y-%m-%d')" --grep='\[auto-save\]' 2>/dev/null || echo "  (none)"
            echo ""
            echo "=== Today's Manual Commits ==="
            git log --oneline --since="$(date '+%Y-%m-%d')" --grep='\[auto-save\]' --invert-grep 2>/dev/null || echo "  (none)"
            ;;
        tags)
            echo "=== Backup Tags ==="
            git tag -l 'backup/*' --sort=-creatordate 2>/dev/null | head -20 || echo "  (none)"
            ;;
        *)
            echo "=== Recent Auto-Save Commits (last 20) ==="
            git log --oneline -20 --grep='\[auto-save\]' 2>/dev/null || echo "  (none)"
            echo ""
            echo "=== Recent Manual Commits (last 10) ==="
            git log --oneline -10 --grep='\[auto-save\]' --invert-grep 2>/dev/null || echo "  (none)"
            echo ""
            echo "=== Backup Tags ==="
            git tag -l 'backup/*' --sort=-creatordate 2>/dev/null | head -10 || echo "  (none)"
            ;;
    esac
}

cmd_show() {
    local commit="${1:?Usage: recover.sh show <commit>}"
    echo "=== Commit Details ==="
    git log --format="Commit: %H%nDate:   %ci%nMsg:    %s" -1 "$commit"
    echo ""
    echo "=== Files Changed ==="
    git diff-tree --no-commit-id -r --stat "$commit"
}

cmd_file() {
    local commit="${1:?Usage: recover.sh file <commit> <path>}"
    local filepath="${2:?Usage: recover.sh file <commit> <path>}"

    echo "Restoring $filepath from $commit..."
    git checkout "$commit" -- "$filepath"
    echo "DONE: $filepath restored. Review the change, then commit if correct."
}

cmd_undo() {
    local count="${1:?Usage: recover.sh undo <N>}"

    echo "=== Commits to revert (newest first) ==="
    git log --oneline -"$count"
    echo ""
    read -p "Revert these $count commits? [y/N] " confirm
    if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
        # Create safety branch first
        local safety_branch="pre-revert-$(date +%Y%m%d-%H%M%S)"
        git branch "$safety_branch"
        echo "Safety branch created: $safety_branch"

        git revert --no-edit HEAD~"${count}"..HEAD
        echo "DONE: $count commits reverted. Safety branch: $safety_branch"
    else
        echo "Aborted."
    fi
}

cmd_snapshot() {
    local branch
    branch=$(git branch --show-current 2>/dev/null || echo "detached")
    local tag="backup/${branch}/$(date '+%Y-%m-%d_%H%M%S')"
    git tag "$tag" HEAD
    echo "Snapshot created: $tag"
    echo "To restore: git checkout -b recovery $tag"
}

cmd_status() {
    echo "=== Auto-Save Health ==="
    echo ""

    # Heartbeat
    if [ -f "$HEARTBEAT_FILE" ]; then
        local last_save now elapsed
        last_save=$(cat "$HEARTBEAT_FILE" 2>/dev/null || echo 0)
        now=$(date +%s)
        elapsed=$((now - last_save))
        local mins=$((elapsed / 60))
        echo "Last auto-save: ${mins} minutes ago ($(date -d @"$last_save" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date -r "$last_save" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "epoch: $last_save"))"
        if [ "$elapsed" -gt 600 ]; then
            echo "  WARNING: Heartbeat is stale (>10 min). Auto-save may not be running!"
        else
            echo "  OK"
        fi
    else
        echo "Last auto-save: NEVER (no heartbeat file)"
    fi
    echo ""

    # Push status
    if [ -f "$PUSH_LOG" ]; then
        echo "Last push result:"
        tail -1 "$PUSH_LOG"
    else
        echo "Push log: not found"
    fi
    echo ""

    # Unpushed commits
    local branch
    branch=$(git branch --show-current 2>/dev/null || echo "")
    if [ -n "$branch" ]; then
        local unpushed
        unpushed=$(git log --oneline "origin/${branch}..HEAD" 2>/dev/null | wc -l | tr -d ' ')
        echo "Unpushed commits: $unpushed"
        if [ "$unpushed" -gt 10 ]; then
            echo "  WARNING: Many unpushed commits. Consider manual push."
        fi
    fi
    echo ""

    # Today's auto-saves
    local today_count
    today_count=$(git log --oneline --since="$(date '+%Y-%m-%d')" --grep='\[auto-save\]' 2>/dev/null | wc -l | tr -d ' ')
    echo "Auto-saves today: $today_count"

    # Backup tags
    local tag_count
    tag_count=$(git tag -l 'backup/*' 2>/dev/null | wc -l | tr -d ' ')
    echo "Backup tags: $tag_count"
}

cmd_diff() {
    local commit="${1:?Usage: recover.sh diff <commit>}"
    git show "$commit" --stat --patch
}

# --- Main ---
command="${1:-}"
shift 2>/dev/null || true

case "$command" in
    list)    cmd_list "$@" ;;
    show)    cmd_show "$@" ;;
    file)    cmd_file "$@" ;;
    undo)    cmd_undo "$@" ;;
    snapshot) cmd_snapshot "$@" ;;
    status)  cmd_status "$@" ;;
    diff)    cmd_diff "$@" ;;
    *)       usage ;;
esac
