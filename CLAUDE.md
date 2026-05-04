# BotifyTrades v9.3.5 — Project Context

## Summary
Multi-broker automated trading bot. Monitors Discord signals, executes trades across 7 brokers (Schwab, Webull, Alpaca, IBKR, Tastytrade, Robinhood, Trading212), manages risk with tiered PT/SL/trailing/OCO brackets. Desktop app built with PyInstaller + PyArmor (user build) or plain PyInstaller (admin build). Web GUI via Flask. ~21K lines in selfbot_webull.py, ~9K in position_monitor.py.

## Tech Stack
- Python 3.11, asyncio, discord.py (selfbot)
- Flask web GUI (PySide6 splash/tray for desktop)
- SQLite (bot_data.db), JSON position cache
- httpx (async HTTP), websockets (streaming)
- PyInstaller + PyArmor (release builds)
- GitHub Actions CI/CD (build-user.yml, build-admin.yml)

## Architecture (Key Files)
| File | Lines | Purpose |
|------|-------|---------|
| `src/selfbot_webull.py` | ~21K | Main bot, Discord handler, broker init |
| `src/risk/position_monitor.py` | ~9K | Risk monitoring, bracket orders, exits |
| `src/risk/risk_types.py` | ~900 | PositionCacheEntry, ChannelRiskSettings |
| `src/risk/risk_engine.py` | ~400 | Pure evaluation logic, ExitDecision |
| `src/brokers/schwab_broker.py` | ~3600 | Schwab API, OCO, HTTP recovery |
| `src/services/schwab_streaming_client.py` | ~520 | Schwab WebSocket streaming |
| `src/services/schwab_data_hub.py` | ~300 | Schwab quote cache/events |
| `src/services/unified_price_hub.py` | ~600 | Cross-broker price aggregation |
| `src/services/broker_sync_service.py` | ~3K | Position reconciliation |
| `src/services/conditional_orders/base.py` | ~2K | Conditional order monitoring |
| `upgrade/version.py` | ~160 | Version: APP_VERSION = "9.3.5" |

## Release Process
```bash
./scripts/release.sh admin 9.3.5   # Private admin build
./scripts/release.sh user 9.3.5    # Public hardened build
```
Repos: DiscordTrader/BotifyTradesv2 (private), DiscordTrader/BotifyTrades (public)

## Active Bug List (Schwab Architect Review — April 2026)
Full HTML report: `docs/schwab_architect_review.html`

### P0 (1) — FIXED April 29, 2026
1. ~~**Event loop starvation**~~ — FIXED: streaming now runs in own thread, cross-loop subscription wrapper added

### P1 (4) — FIXED April 29, 2026
2. ~~**OCO cancel result ignored**~~ — FIXED: cancel result checked, abort on failure to prevent double-sell
3. ~~**Stale broker_pt_order_id**~~ — FIXED: cleared on OCO re-place failure
4. ~~**get_order_status bypasses rate limiter**~~ — FIXED: routed through `_make_request()`
5. ~~**Double cancel sweep per sell**~~ — FIXED: redundant second sweep removed

### P2 (9) — FIXED April 29, 2026
6. ~~Deferred SL stale price~~ — FIXED: uses dynamic_sl_price or early_stop_price
7. ~~Dynamic SL sync gated by wrong field~~ — FIXED: checks broker_oco_order_id too
8. ~~No standalone SL after cascade~~ — FIXED: same guard fix as #7
9. ~~`_extract_broker` missing Schwab~~ — FIXED: added Schwab, Tastytrade, Robinhood, Trading212
10. ~~`get_option_chain` bypasses rate limiter~~ — FIXED: routed through `_make_request()`
11. ~~SELL_SHORT misclassified as exit~~ — FIXED: removed from is_exit check
12. ~~Streaming `_connected` before subscriptions~~ — FIXED: set after subscriptions restored
13. ~~Streaming `stop()` no cleanup~~ — FIXED: ws.close() + thread.join()
14. ~~`_fetch_streamer_info` bypasses rate limiter~~ — FIXED: routed through `_make_request()`

### P3 (6) — not yet fixed, minor, see review doc

## Uncommitted Changes
- All v9.4.0 changes committed in release

## Code Style
- No comments unless WHY is non-obvious
- Minimal abstractions — three similar lines > premature helper
- Print-based logging with `[BROKER]` / `[RISK]` / `[UPH]` prefixes + emoji markers
- Snake_case everywhere, `_private` prefix convention

## Session Management (AUTO — follow these every session)

### On Session Start
- This file loads automatically. If the user's first message needs prior context, read `docs/progress.md` and `session_summary.md` before responding.

### Every ~30-40 Messages
- Proactively tell the user: "We're at ~N messages — recommend running `/compact` to save tokens."
- After compact, auto-save the compacted summary to `session_summary.md`.

### On Major Milestones
- When a fix is implemented, a feature is complete, or a review is done, append a dated entry to `docs/progress.md` automatically — don't wait for the user to ask.
- Update the bug list above if bugs are fixed (mark as FIXED with date).
- Update `Uncommitted Changes` section after commits.

### On Session End (user says "done", "bye", "that's all", etc.)
- Auto-save final state to `session_summary.md`.
- Append session summary to `docs/progress.md`.
- Remind user: "Progress saved. Next session just open a new chat — CLAUDE.md loads automatically."

### Token Budget Rules
- Never re-read files already in context from this session.
- Use `@file` references in responses instead of pasting large blocks.
- For files >500 lines, read only the relevant section (offset/limit).
- Prefer grep to find line numbers first, then targeted reads.
