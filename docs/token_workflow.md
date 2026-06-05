# Token-Saving Workflow Reference

## Auto (handled by CLAUDE.md instructions)
- Session start: CLAUDE.md auto-loads, reads progress.md if needed
- Every ~30-40 msgs: Claude prompts for `/compact`
- Milestones: Claude auto-appends to docs/progress.md
- Session end: Claude auto-saves session_summary.md + progress.md

## Manual (user triggers)
| Action | When | Command |
|--------|------|---------|
| Compact context | Every ~30-40 msgs | `/compact` |
| Load prior context | New session start | `@docs/progress.md` `@session_summary.md` |
| Full history | Deep investigation | `@docs/progress.md` |

## Files
| File | Auto-loaded? | Purpose |
|------|-------------|---------|
| `CLAUDE.md` | Yes (every session) | Project context + instructions (<5K tokens) |
| `docs/progress.md` | No (load with @) | Running log of all sessions |
| `session_summary.md` | No (load with @) | Last session snapshot |
| `docs/schwab_architect_review.html` | No | Schwab bug review document |
| `docs/AI_ARCHITECTURE_PROMPT.md` | No | Architecture reference |
