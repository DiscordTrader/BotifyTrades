# BotifyTradesv2 - Claude Code Instructions

## Project Context
This is an **industry-grade live trading bot** with Schwab broker integration. Code changes affect real money positions. Treat all modifications with extreme care.

## Active Implementation Plan
There is an active auto-save & recovery system implementation in progress:
- **Plan file:** `docs/AUTOSAVE_IMPLEMENTATION_PLAN.md`
- **On every new session:** Read the plan file, check the Task Checklist section, and report which phase/task is next
- **After completing any task:** Update the checkbox from `[ ]` to `[x]` in the plan file

## Critical Rules
1. **NEVER use `git add -A` or `git add .`** — always stage specific files or directories
2. **NEVER commit** these file types: `.db-wal`, `.db-shm`, `.position_cache.json`, `.encryption_key`, `.schwab_salt`, `schwab_token*`, `wizard_credentials.json`, `did.bin`, `cookies.txt`, `*.tar.gz`, `*.zip`
3. **NEVER run destructive git commands** (`reset --hard`, `push --force`) without explicit user confirmation
4. **Always validate Python syntax** (`python -m py_compile`) before committing `.py` files
5. **Test changes** before reporting them complete — this is a live trading system

## Key Directories
- `src/brokers/` — Broker integrations (Schwab, Trading212)
- `src/risk/` — Risk management engine, position monitoring
- `src/services/` — Core services (Discord, webhooks)
- `gui_app/` — Web UI (Flask)
- `scripts/` — Build, release, maintenance scripts

## Branch Strategy
- `main` — stable, reviewed code only
- `fix/*`, `feature/*` — development branches
- Auto-save commits use `[auto-save]` prefix for easy identification
