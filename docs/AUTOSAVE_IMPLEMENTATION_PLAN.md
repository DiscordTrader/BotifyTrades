# BotifyTradesv2 Auto-Save & Recovery System - Implementation Plan

> **Status:** IN PROGRESS (Phase 1+2 COMPLETE, Phase 3-4 remaining)  
> **Created:** 2026-04-25  
> **Last Updated:** 2026-04-25  
> **Branch:** fix/conditional-orders-defaults  
> **Priority:** CRITICAL - Live trading system, changes affect real money

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Phase 1: Immediate Prerequisites](#phase-1-immediate-prerequisites)
4. [Phase 2: Build Auto-Save System](#phase-2-build-auto-save-system)
5. [Phase 3: Hardening](#phase-3-hardening-first-week)
6. [Phase 4: Mature Operations](#phase-4-mature-operations-first-month)
7. [Recovery Procedures](#recovery-procedures)
8. [Gap Analysis Reference](#gap-analysis-reference)
9. [Task Checklist](#task-checklist)

---

## Overview

### Problem
- No automated commit mechanism; changes can be lost on crash/power failure
- ~50+ sensitive/runtime files (encryption keys, broker tokens, DB WAL files) are tracked in git
- Secrets already exist in git history on GitHub remote
- `release.sh` uses `git add -A` which bypasses all safety guards
- `PositionCache.save()` has no thread safety or atomic writes
- No validation gate before commits or pushes

### Solution: 3-Layer Protection + Recovery

```
Layer 1: .gitignore hardening + untrack sensitive files
Layer 2: scripts/autosave.sh (debounced, allowlisted, validated)
Layer 3: Claude Code hooks + Windows Task Scheduler
Layer 4: .git/hooks/pre-commit (allowlist-based safety net)
Layer 5: Recovery tools (scripts/recover.sh + daily backup tags)
```

---

## Architecture

### Auto-Save Flow

```
Code Change (Claude Edit/Write OR manual edit)
    |
    v
+------------------------------------------+
| PostToolUse Hook / Task Scheduler (5min)  |
| -> runs scripts/autosave.sh              |
+------------------------------------------+
    |
    v
+------------------------------------------+
| MUTEX CHECK (flock-based)                |
| -> skip if another instance running      |
+------------------------------------------+
    |
    v
+------------------------------------------+
| DEBOUNCE CHECK (30s, bypassed by FORCE)  |
| -> skip if last save < 30s ago           |
+------------------------------------------+
    |
    v
+------------------------------------------+
| STAGE (directory-scoped, NOT git add -u) |
| -> git add -u -- src/ gui_app/ scripts/  |
|    tests/ ui/ upgrade/ docs/ .github/    |
| -> untracked files: allowlist regex only |
+------------------------------------------+
    |
    v
+------------------------------------------+
| VALIDATE                                 |
| -> python -m py_compile on all .py files |
| -> block if syntax errors found          |
+------------------------------------------+
    |
    v
+------------------------------------------+
| PRE-COMMIT HOOK (allowlist gate)         |
| -> only permit safe file extensions      |
| -> only permit safe directories          |
| -> block everything else                 |
+------------------------------------------+
    |
    v
+------------------------------------------+
| COMMIT                                   |
| -> [auto-save][area] branch | time | N   |
| -> includes changed filenames in body    |
+------------------------------------------+
    |
    v
+------------------------------------------+
| DAILY BACKUP TAG (once per day)          |
| -> backup/<branch>/YYYY-MM-DD           |
+------------------------------------------+
    |
    v
+------------------------------------------+
| PUSH (sync, with timeout + no-prompt)    |
| -> GIT_TERMINAL_PROMPT=0 timeout 30     |
| -> log result to .autosave_push.log      |
+------------------------------------------+
    |
    v
+------------------------------------------+
| HEARTBEAT                                |
| -> write timestamp to .autosave_heartbeat|
+------------------------------------------+
```

### Session End Flow

```
Claude session ends / VS Code closes
    |
    v
+------------------------------------------+
| Stop Hook                                |
| -> FORCE_SAVE=1 bash scripts/autosave.sh |
| -> bypasses debounce, always commits     |
+------------------------------------------+
```

---

## Phase 1: Immediate Prerequisites

> **Goal:** Remove all sensitive/runtime files from git tracking and fix critical code issues.  
> **Must complete before enabling auto-save.**

### Task 1.1: Harden .gitignore
**File:** `.gitignore`  
**Status:** [ ] NOT STARTED

Add these blocks to the existing `.gitignore`:

```gitignore
# ===== Runtime data (live bot) =====
.position_cache.json
sod_snapshots.json
executed_trades.json
.permanent_failures.json

# SQLite WAL/journal files
*.db-shm
*.db-wal
*.db-journal

# Database backups
bot_data.db.*
bot_data_corrupted.*

# ===== Secrets & credentials =====
.encryption_key
src/.encryption_key
.schwab_salt
schwab_tokens.enc
wizard_credentials.json
did.bin
src/did.bin
cookies.txt

# ===== Large data files =====
extracted_*.json

# ===== Package archives =====
*.tar.gz
*.zip
*.pkg
*.pyz
india_bot_package/
india_trading_bot_package/

# ===== Build artifacts =====
build/botifytrades/

# ===== Auto-save infrastructure =====
.autosave_heartbeat
.autosave_push.log
.autosave.lock
```

### Task 1.2: Untrack Sensitive Files from Git
**Status:** [ ] NOT STARTED

Run these commands (files stay on disk, just removed from git tracking):

```bash
# Runtime data
git rm --cached .position_cache.json
git rm --cached executed_trades.json .permanent_failures.json

# SQLite WAL files
git rm --cached bot_data.db-shm bot_data.db-wal
git rm --cached bot_data_corrupted.db-shm bot_data_corrupted.db-wal
git rm --cached bot_data.db.backup_20260211_192454 bot_data.db.corrupted_backup bot_data.db.new_backup

# Secrets & credentials
git rm --cached .encryption_key src/.encryption_key
git rm --cached .schwab_salt
git rm --cached schwab_tokens.enc wizard_credentials.json
git rm --cached did.bin src/did.bin
git rm --cached cookies.txt

# Large data files (unicode filenames - use loop)
git ls-files | grep '^extracted_' | while IFS= read -r f; do git rm --cached "$f"; done

# Package archives
git rm --cached DiscordWebullBot_LocalPackage.tar.gz Discord_Trading_Bot_EXE_Package.tar.gz
git rm --cached india_bot_package.tar.gz india_bot_package.zip india_trading_bot_package.zip
git rm --cached license_server_package.tar.gz 2>/dev/null || true

# Build artifacts (if tracked)
git ls-files -- build/botifytrades/ | while IFS= read -r f; do git rm --cached "$f"; done
```

Commit:
```bash
git add .gitignore
git commit -m "chore: untrack runtime data, secrets, and large binaries

Removes ~50+ files from git tracking (kept on disk):
- SQLite WAL/SHM files and DB backups
- Position cache, executed trades, failure logs
- Encryption keys, salts, device IDs, credentials
- Discord channel extract JSONs
- Package archives and build artifacts

Updated .gitignore to prevent re-addition.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

### Task 1.3: Fix release.sh - Remove `git add -A`
**File:** `scripts/release.sh` (line ~117)  
**Status:** [ ] NOT STARTED

Replace:
```bash
git add -A
```
With explicit staging:
```bash
git add src/ gui_app/ scripts/ tests/ ui/ upgrade/ docs/ .github/ \
       requirements.txt Makefile pytest.ini .gitignore CLAUDE.md README.md
```

### Task 1.4: Fix PositionCache.save() Thread Safety
**File:** `src/risk/position_cache.py` (line ~315)  
**Status:** [ ] NOT STARTED

Changes needed:
1. Acquire `self._cache_lock` before iterating `self._cache.items()` in `save()`
2. Use atomic file write: write to `.position_cache.json.tmp`, then `os.replace()` to final path
3. This prevents half-written JSON from being read by the bot on restart

```python
def save(self):
    with self._cache_lock:
        data = {k: v.to_dict() for k, v in self._cache.items()}
    tmp_path = self._cache_file + '.tmp'
    with open(tmp_path, 'w') as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp_path, self._cache_file)
```

### Task 1.5: Credential Rotation (Manual - Developer Action)
**Status:** [ ] NOT STARTED

> **WARNING:** `.encryption_key`, `.schwab_salt`, `schwab_tokens.enc`, `wizard_credentials.json` are ALL in git history on the GitHub remote. Even after `git rm --cached`, anyone with repo access can retrieve them from historical commits.

**Developer must:**
1. Rotate Schwab API client credentials and tokens
2. Generate a new encryption key (Fernet)
3. Re-encrypt tokens with new key
4. Update license key if needed
5. Schedule `git filter-repo` cleanup (Phase 3) to purge history

---

## Phase 2: Build Auto-Save System

> **Goal:** Create the auto-save infrastructure with all safety guards.  
> **Start only after Phase 1 is complete.**

### Task 2.1: Create autosave.sh
**File:** `scripts/autosave.sh`  
**Status:** [ ] NOT STARTED

Key design requirements:
- **Mutex:** Use `flock` (not just debounce) to prevent concurrent runs
- **Debounce:** 30 seconds default, bypassed by `FORCE_SAVE=1`
- **Directory-scoped staging:** `git add -u -- src/ gui_app/ scripts/ tests/ ui/ upgrade/ docs/ .github/ qa/`
- **Allowlist for untracked files:** Only `\.(py|js|jsx|ts|tsx|html|css|sh|bat|md|txt|yml|yaml|ini|toml|cfg|nix|spec|svg)$`
- **Root config allowlist:** `.gitignore`, `CLAUDE.md`, `requirements.txt`, `Makefile`, `pytest.ini`
- **Syntax validation:** `python -m py_compile` on all staged `.py` files before commit
- **Semantic commit message:** `[auto-save][risk] branch | time | N file(s)` with filenames in body
- **Daily backup tag:** `backup/<branch>/YYYY-MM-DD` (lightweight, created once per day)
- **Synchronous push with timeout:** `GIT_TERMINAL_PROMPT=0 timeout 30 git push`
- **Push logging:** Append result to `.autosave_push.log`
- **Heartbeat:** Write epoch timestamp to `.autosave_heartbeat`
- **Branch guard:** Refuse to auto-commit on `main` or `master`
- **Guard checks:** `.git/index.lock`, rebase/merge state, detached HEAD

### Task 2.2: Create autosave.bat (Windows wrapper)
**File:** `scripts/autosave.bat`  
**Status:** [ ] NOT STARTED

Purpose: Windows Task Scheduler cannot run `.sh` files directly. This wrapper locates `bash.exe` and invokes `autosave.sh`.

```bat
@echo off
setlocal

:: Try common Git Bash locations
set "BASH_EXE="
if exist "C:\Program Files\Git\bin\bash.exe" set "BASH_EXE=C:\Program Files\Git\bin\bash.exe"
if exist "C:\Program Files (x86)\Git\bin\bash.exe" set "BASH_EXE=C:\Program Files (x86)\Git\bin\bash.exe"

:: Try PATH
if "%BASH_EXE%"=="" (
    where bash.exe >nul 2>&1
    if %ERRORLEVEL% equ 0 set "BASH_EXE=bash.exe"
)

if "%BASH_EXE%"=="" (
    echo ERROR: bash.exe not found >> "%~dp0..\autosave_errors.log"
    exit /b 1
)

cd /d "%~dp0.."
"%BASH_EXE%" scripts/autosave.sh
```

### Task 2.3: Create pre-commit hook (ALLOWLIST-based)
**File:** `.git/hooks/pre-commit`  
**Status:** [ ] NOT STARTED

Key design: **Allowlist, not blocklist.** Only permit known-safe file types and directories.

```bash
#!/usr/bin/env bash
# ALLOWLIST-based pre-commit hook
# Only permit source code files in approved directories

staged_files=$(git diff --cached --name-only)

SAFE_DIR_PATTERN='^(src/|gui_app/|scripts/|tests/|ui/|upgrade/|docs/|\.github/|qa/|build/.*\.spec)'
SAFE_ROOT_FILES='^(\.gitignore|CLAUDE\.md|README\.md|requirements\.txt|Makefile|pytest\.ini|\.replit|package\.json|tsconfig\.json)$'
SAFE_EXT_PATTERN='\.(py|js|jsx|ts|tsx|html|css|sh|bat|md|txt|yml|yaml|ini|toml|cfg|nix|spec|svg|json)$'

blocked=""
while IFS= read -r file; do
    [ -z "$file" ] && continue
    
    # Allow files in safe directories with safe extensions
    if echo "$file" | grep -qE "$SAFE_DIR_PATTERN"; then
        if echo "$file" | grep -qE "$SAFE_EXT_PATTERN"; then
            continue
        fi
    fi
    
    # Allow specific root files
    if echo "$file" | grep -qE "$SAFE_ROOT_FILES"; then
        continue
    fi
    
    # Allow .claude/settings.json
    if [ "$file" = ".claude/settings.json" ]; then
        continue
    fi
    
    blocked="$blocked\n  $file"
done <<< "$staged_files"

if [ -n "$blocked" ]; then
    echo "ERROR: Pre-commit hook blocked non-allowlisted files:"
    echo -e "$blocked"
    echo ""
    echo "Only source code in approved directories is permitted."
    echo "If this is intentional, review and update the pre-commit hook."
    exit 1
fi
```

### Task 2.4: Configure Claude Code hooks
**File:** `.claude/settings.json`  
**Status:** [ ] NOT STARTED

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "bash scripts/autosave.sh 2>/dev/null || true"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "FORCE_SAVE=1 bash scripts/autosave.sh 2>/dev/null || true"
          }
        ]
      }
    ]
  }
}
```

Note: `|| true` ensures hook failure never blocks Claude Code operation.

### Task 2.5: Create Windows Task Scheduler job
**Status:** [ ] NOT STARTED

```powershell
$action = New-ScheduledTaskAction `
    -Execute "C:\VSCode\Cluade_Botify\BotifyTradesv2\scripts\autosave.bat" `
    -WorkingDirectory "C:\VSCode\Cluade_Botify\BotifyTradesv2"

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 365)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2)

Register-ScheduledTask `
    -TaskName "BotifyTradesv2_AutoSave" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Auto-save source code changes every 5 minutes"
```

### Task 2.6: Create recover.sh
**File:** `scripts/recover.sh`  
**Status:** [ ] NOT STARTED

Commands:
```
Usage: bash scripts/recover.sh <command> [args]

  list                    List all recovery points (auto-saves + tags)
  list today              List today's recovery points only
  show <commit>           Show what changed in a specific commit
  file <commit> <path>    Restore a single file from a commit
  undo <N>                Revert last N auto-save commits (creates new commits)
  snapshot                Create a manual backup tag right now
  status                  Show auto-save health (last run, push status, heartbeat)
```

---

## Phase 3: Hardening (First Week)

> **Goal:** Close remaining security and operational gaps.

### Task 3.1: Purge Secrets from Git History
**Status:** [ ] NOT STARTED

```bash
# Install git-filter-repo
pip install git-filter-repo

# Backup first
git clone --mirror . ../BotifyTradesv2-backup-$(date +%Y%m%d)

# Purge sensitive files from ALL history
git filter-repo --invert-paths \
    --path .encryption_key \
    --path src/.encryption_key \
    --path .schwab_salt \
    --path schwab_tokens.enc \
    --path wizard_credentials.json \
    --path did.bin \
    --path src/did.bin \
    --path cookies.txt \
    --path bot_data.db-shm \
    --path bot_data.db-wal \
    --path bot_data_corrupted.db-shm \
    --path bot_data_corrupted.db-wal \
    --path bot_data.db.backup_20260211_192454 \
    --path bot_data.db.corrupted_backup \
    --path bot_data.db.new_backup \
    --path .position_cache.json \
    --path executed_trades.json \
    --path .permanent_failures.json \
    --path sod_snapshots.json \
    --path DiscordWebullBot_LocalPackage.tar.gz \
    --path Discord_Trading_Bot_EXE_Package.tar.gz \
    --path india_bot_package.tar.gz \
    --path india_bot_package.zip \
    --path india_trading_bot_package.zip \
    --path license_server_package.tar.gz \
    --force

# Force push ALL branches
git push origin --force --all
git push origin --force --tags
```

**WARNING:** This rewrites ALL commit hashes. All existing clones become invalid.

### Task 3.2: Add Health Check / Heartbeat Monitor
**Status:** [ ] NOT STARTED

- autosave.sh writes epoch to `.autosave_heartbeat` on every successful run
- Add a check in the bot's startup: if heartbeat is stale (>10 min), log a warning
- Optional: desktop notification via PowerShell toast

### Task 3.3: Improve Push Error Handling
**Status:** [ ] NOT STARTED

- Use `GIT_TERMINAL_PROMPT=0` to prevent credential popups
- Use `timeout 30 git push` (synchronous, not background)
- Log results to `.autosave_push.log`
- Create `.push_failed` sentinel on failure for visibility

### Task 3.4: Add Branch Safeguards
**Status:** [ ] NOT STARTED

In autosave.sh:
- Refuse to auto-commit on `main` or `master`
- Warn if branch name doesn't match expected patterns
- Log branch name in commit message for traceability

---

## Phase 4: Mature Operations (First Month)

> **Goal:** Long-term maintainability and operational excellence.

### Task 4.1: WIP Branch Separation
**Status:** [ ] NOT STARTED

- Auto-save commits go to `wip/<branch>` prefix branch
- Feature branch updated only via explicit merge/PR
- Bot runs from a `stable` branch with tested code only

### Task 4.2: Bot File-Watcher for Live Rollback
**Status:** [ ] NOT STARTED

- Monitor `src/risk/*.py` and `src/brokers/*.py` for disk changes
- Log WARNING if files change while bot is running
- Optional: graceful restart trigger

### Task 4.3: Archive Branches Before Squash
**Status:** [ ] NOT STARTED

Before monthly cleanup:
- Create `archive/YYYY-MM` branch preserving full granular history
- Never squash commits touching `src/risk/`, `src/brokers/`, `src/services/`

### Task 4.4: Monthly Cleanup Script
**File:** `scripts/cleanup_autosaves.sh`  
**Status:** [ ] NOT STARTED

- Last 30 days: keep every auto-save commit
- 30-90 days: squash into 1 commit per day
- 90+ days: squash into 1 commit per week
- Daily backup tags: clean up tags older than 6 months
- Always preserve non-auto-save commits

---

## Recovery Procedures

### Quick Rollback (Last Change Broke Something)

```bash
# Undo the last auto-save
git revert HEAD --no-edit

# Undo last 3 auto-saves
git revert HEAD~3..HEAD --no-edit
```

### File-Level Recovery (One File is Bad)

```bash
# Restore single file from 2 commits ago
git checkout HEAD~2 -- src/brokers/schwab_broker.py

# Restore from specific commit
git checkout 5fe8686 -- src/brokers/schwab_broker.py

# View file at any point in time
git show 5fe8686:src/brokers/schwab_broker.py
```

### Time-Travel Recovery (Was Working Earlier Today)

```bash
# Find the commit before things broke
git log --oneline --before="2026-04-25 14:30" -5

# Create recovery branch from that point
git checkout -b recovery/pre-bug <good-commit-hash>

# Or use daily backup tag
git checkout -b recovery/pre-bug backup/fix/conditional-orders-defaults/2026-04-25
```

### Emergency Full Reset

```bash
# ALWAYS create safety branch first
git branch emergency-backup-$(date +%Y%m%d-%H%M)

# Reset to main
git reset --hard origin/main
```

### Check Auto-Save Health

```bash
bash scripts/recover.sh status
# Shows: last auto-save time, push status, heartbeat age, unpushed commits
```

---

## Gap Analysis Reference

### Critical Gaps (Must Fix in Phase 1)

| ID | Gap | Impact | Fix Task |
|----|-----|--------|----------|
| 1.1 | Position cache race: bot write vs git stage | Corrupt JSON -> naked positions | 1.2, 1.4 |
| 1.2 | SQLite WAL tracked in git | Corrupt DB on checkout/recovery | 1.1, 1.2 |
| 1.3 | `git add -u` bypasses allowlist for tracked files | Secrets committed | 1.2 |
| 4.1 | Secrets in git history on remote | Broker account compromise | 1.5, 3.1 |
| 4.2 | `release.sh` uses `git add -A` | Bypasses all guards | 1.3 |

### High Gaps (Must Fix in Phase 2)

| ID | Gap | Impact | Fix Task |
|----|-----|--------|----------|
| 3.1 | Concurrent autosave invocations | Race on index.lock | 2.1 (flock) |
| 3.2 | PositionCache.save() no thread safety | Half-written JSON | 1.4 |
| 5.1 | Background push hangs on Windows | Silent push failure | 3.3 |
| 6.2 | No syntax validation before push | Broken code pushed | 2.1 (py_compile) |
| 8.1 | Bash script won't run from Task Scheduler | Silent failure | 2.2 |
| 9.1 | No health check / heartbeat | Undetected failure | 3.2 |
| 9.4 | Auto-push bypasses PR review | Unreviewed bugs in prod | 4.1 |

### Medium Gaps (Phase 3-4)

| ID | Gap | Impact | Fix Task |
|----|-----|--------|----------|
| 2.3 | 10GB waste in git history | Slow operations | 3.1 |
| 5.2 | Daily backup tags accumulate | Tag enumeration slows | 4.4 |
| 5.3 | Branch divergence risk | Wrong branch auto-committed | 3.4 |
| 6.1 | git revert fails with conflicts | Recovery not "quick" | Use file-level recovery |
| 6.3 | Monthly squash destroys granularity | Can't recover mid-day state | 4.3 |
| 9.2 | Generic commit messages | Hard to find specific changes | 2.1 (semantic) |
| 9.3 | No bot integration for rollback | Bot uses stale in-memory code | 4.2 |

---

## Task Checklist

### Phase 1 - Immediate Prerequisites
- [x] **1.1** Harden .gitignore with runtime/secrets/binary rules (2026-04-25)
- [x] **1.2** Untrack ~108 sensitive/runtime/binary files via `git rm --cached` (2026-04-25)
- [x] **1.3** Fix `release.sh` - replace `git add -A` with explicit staging (2026-04-25)
- [x] **1.4** Fix `PositionCache.save()` thread safety + atomic writes (2026-04-25)
- [ ] **1.5** Rotate credentials (Schwab tokens, encryption key) - DEVELOPER ACTION

### Phase 2 - Build Auto-Save System
- [x] **2.1** Create `scripts/autosave.sh` with all safety guards (2026-04-25)
- [x] **2.2** Create `scripts/autosave.bat` (Windows wrapper) (2026-04-25)
- [x] **2.3** Create `.git/hooks/pre-commit` (allowlist-based) (2026-04-25)
- [x] **2.4** Configure `.claude/settings.json` hooks (2026-04-25)
- [x] **2.5** Create Windows Task Scheduler job (2026-04-25)
- [x] **2.6** Create `scripts/recover.sh` recovery tool (2026-04-25)

### Phase 3 - Hardening (First Week)
- [ ] **3.1** Purge secrets from git history (`git filter-repo`)
- [ ] **3.2** Add health check / heartbeat monitor
- [ ] **3.3** Improve push error handling (no-prompt, timeout, logging)
- [ ] **3.4** Add branch safeguards (refuse main, warn on unexpected)

### Phase 4 - Mature Operations (First Month)
- [ ] **4.1** WIP branch separation (auto-save -> wip/, manual merge -> feature)
- [ ] **4.2** Bot file-watcher for live rollback detection
- [ ] **4.3** Archive branches before squash cleanup
- [ ] **4.4** Monthly cleanup script

---

## How to Resume After Session Change / Crash

This plan is designed to survive any interruption:

1. **This file** (`docs/AUTOSAVE_IMPLEMENTATION_PLAN.md`) contains the complete plan with checkboxes
2. **CLAUDE.md** at the project root tells Claude to read this plan on every new session
3. **Memory system** (`~/.claude/projects/.../memory/`) stores a pointer to this plan

### To resume in any new Claude session:
```
"Continue implementing the auto-save plan from docs/AUTOSAVE_IMPLEMENTATION_PLAN.md"
```

Claude will:
1. Read this file
2. Find the first unchecked `[ ]` task
3. Continue from where we left off

### After completing a task:
The task checkbox in this file will be updated from `[ ]` to `[x]` with a completion date.
