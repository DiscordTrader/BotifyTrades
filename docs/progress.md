# BotifyTrades Progress Log

## Session: June 8-9, 2026 — IBKR Event Loop Fix + Temple Parser SL/Target Bugs

### FIX: IBKR Event Loop Starvation (v11.1.8)
- **Problem**: All `ib_insync` calls (`positions()`, `portfolio()`, `openTrades()`, `trades()`, `placeOrder()`, `tickers()`) are synchronous and blocked the asyncio event loop, starving `pendingTickersEvent` for real-time prices
- **Impact**: IBKR sync showed 0 positions, bracket orders looped on "unreachable", conditional order prices stuck
- **Fix**: Wrapped 16 blocking calls across 4 files with `asyncio.to_thread()`: `ibkr_broker.py` (10), `broker_sync_service.py` (4), `position_monitor.py` (6), `ibkr_data_hub.py` (2)
- **Also**: Added `MAX_ORDER_SIZE = 70000` cap for IBKR non-algo orders (order rejection error 201 at 131K shares)
- **Released**: v11.1.8 pushed to private + public repos, admin + user builds triggered

### FIX: Temple Parser SL Line-Boundary Bleed
- **Problem**: `sl_raw_text = text[text.index('❌'):text.index('❌')+40]` grabbed 40 chars past ❌, bleeding into 🎯 targets line. For `❌ 1.38\n🎯 5% 10% 15%`, the `%` from targets caused price SL $1.38 to be misclassified as 1.38%
- **Fix**: Limit SL slice to the ❌ line only (up to `\n` boundary)
- **Validated**: 102 real signals from ⚡│zz channel — all 49 fixed-price SLs and 7 percent SLs classified correctly

### FIX: Multi-Dash Target Parsing
- **Problem**: `🎯 1.20-1.50-1.70-2.00` only captured [1.2, 1.5] — the split regex didn't handle `-` separators, and the range regex only matched 2 numbers
- **Fix**: Detect 3+ numbers in a dash-separated part and extract all; preserve 2-number range behavior
- **Validated**: `1.20-1.50-1.70-2.00` → [1.2, 1.5, 1.7, 2.0], `2.60-3.00` → [2.6, 3.0] (range still works)

## Session: May 29, 2026 — PANW Risk Analysis + TEMPLE-BOOM Format Filter + Webull Diagnosis

### ANALYSIS + FIX: PANW 280C 05/29 — Risk Engine Post-Mortem
- **Trade**: BTO $0.19 → STC $0.18 (-5.26%), held 3 min 14 sec, dynamic_sl trigger
- **max_pnl_seen**: 47.37% (DB), actual peak 117%+ (user confirmed). System only captured 47% from slow REST polls.
- **Root cause 1 (Bug)**: New options NOT dynamically subscribed to Schwab streaming after BTO fill — only equities got subscribed. Options relied on 5s REST polls, missing 0DTE spikes.
- **Root cause 2 (Bug)**: Tiered targets + ratchet SL only checked `pnl_pct` (current snapshot price), not `max_pnl_seen` (interval peak). Price spiked to 117% between evaluations but by eval time was only ~40%.
- **Impact**: Ratchet SL computed from 40% snapshot → $0.2223 (+17%). Should have used 117% peak → $0.3686 (+94%). Loss of ~$55 per contract.
- **Fix 1**: Dynamic option streaming subscription via `schwab_data_hub.request_subscribe_options()` + drain loop in streaming client. Position monitor now pushes option raw_symbols to Schwab streaming when new positions detected.
- **Fix 2**: Tier evaluation uses `peak_pnl = max(pnl_pct, max_pnl_seen)` to MARK tiers. Partial sells still require current price confirmation. Ratchet SL in escalation_only mode uses `peak_pnl` for SL calculation.
- **Files**: `schwab_data_hub.py`, `schwab_streaming_client.py`, `position_monitor.py`, `risk_engine.py`
- **Tests**: 539 passed, 0 failures. Verified PANW scenario: 117% peak → all 4 tiers hit → ratchet SL at $0.3686. Equity behavior unchanged.

### FEATURE: AbTrades Signal Parser (abi channel)
- **New file**: `src/signals/abtrades_parser.py` — standalone parser, no existing code modified
- **3 formats**: `abtrades_entry` (pri 82), `abtrades_trim` (pri 83), `abtrades_exit` (pri 84)
- **Entry**: `**$SYMBOL MM/DD STRIKEc PRICE**` — bold-wrapped, extracts SL/PT/qty(xN)/expiry_year
- **Trim**: `$SYMBOL STRIKEc NN%` (non-bold) — profit update with percentage
- **Exit**: Bidirectional `ALL OUT`/`closing remaining` — handles symbol before OR after exit phrase
- **Architect gap review**: Fixed 7 gaps including BLOCKER (option signals invisible to execution pipeline), 6 missed exits (reversed symbol order), LEAPS expiry_year, PT extraction crash
- **Pipeline fix**: `selfbot_webull.py` now routes `abtrades_*` option signals to `opt` dict for broker execution (same pattern as Sir Goldman)
- **Validation**: 41 entries, 12 exits (was 6 before fix), 141 trims from 1000 real messages. 588 tests pass.
- **Channel setup**: Set `allowed_signal_formats = '["abtrades_entry","abtrades_trim","abtrades_exit"]'` to prevent cross-parser collision

### FIX: TEMPLE-BOOM False Positive Signal Filtering
- **Problem**: Channel updates/commentary parsed as trade signals by loose regex patterns
- **Fix**: Added per-channel `allowed_signal_formats` column to channels table. TEMPLE-BOOM set to only accept structured signals (✅/❌/🎯 format)
- **Files**: `gui_app/database.py` (migration), `src/selfbot_webull.py` (filter logic after `parse_all_with_registry()`)

### FIX: GMEX "clear break of" Pattern Not Matching
- **Problem**: "✅ clear break of 3.50" failed structured entry regex
- **Fix**: Added `(?:clear[ \t]+)?` before `break` in both `temple_parser.py` and `signal_format_registry.py`

### DIAGNOSED: Webull Connection Red on Dashboard
- **Problem**: Webull shows red on Multi-Broker Dashboard despite account balance showing
- **Root cause**: Credentials corrupted from encryption key rotation (email/password empty, refresh_token 5 chars)
- **Action needed**: Re-enter Webull credentials via GUI

### FIX: Phoenix/TEMPLE-BOOM Missing WEBULL in enabled_brokers
- **Problem**: REPL conditional order only created for Schwab, not Webull
- **Root cause**: Phoenix channel had `enabled_brokers: ["SCHWAB"]`
- **Fix**: Added WEBULL to phoenix and TEMPLE-BOOM enabled_brokers

## Session: May 26, 2026 — Public Repo Security Cleanup

### CRITICAL: Source Code Exposed on Public Repo
- **Problem**: `DiscordTrader/BotifyTrades` (public) had 768 files including full Python source, `.encryption_key`, `.schwab_salt`, `schwab_tokens.enc`, and `license_server/` pushed directly to `main` branch across 30 commits by `udayerpdba`.
- **Root cause**: Direct `git push` of source code to public repo. CI/CD (`build-user.yml`) correctly only publishes release binaries via `softprops/action-gh-release` — it never pushes source.
- **Fix**: Created orphan branch `releases-only` with only `README.md` (download links) + `.gitignore`, force-pushed as `main`. All 35 releases (v9.1.3 through v10.2.4) with 4-platform binaries confirmed intact.
- **Status**: All 4 phases COMPLETE.
- **Note**: 1 fork exists that still has old source code — cannot be controlled from upstream.

### Phase 3: Credential Rotation
- **`.encryption_key`**: Regenerated (new 44-byte Fernet key). Old config.enc is invalidated — broker creds must be re-entered on next bot start.
- **`.schwab_salt`**: Regenerated (new 16-byte random salt). Old `schwab_tokens.enc` deleted — Schwab OAuth re-authentication required.
- **`.gitignore` fixed**: Added `.encryption_key`, `.schwab_salt`, `schwab_tokens.enc`, `config.enc` — these should never have been tracked.
- **Git untracked**: All 3 files removed from git index via `git rm --cached`.

### Phase 4: Branch Protection
- Public repo `main` branch now requires 1 PR approval, enforced for admins, force pushes and deletions blocked.

### FIX: TEMPLE-BOOM "SYMBOL in at PRICE" format not detected
- **Problem**: `MREO in at 2.50`, `NCEL in at 3.80 @Momentum`, `YMAT in again at 1.15 @Swing` — all missed.
- **Root cause**: `phoenix_entry_in_at` (pri 62) regex `\bin\s+([A-Z])` starts from the word "in", capturing the NEXT word as symbol (e.g. "AT" or "AGAIN"). The existing `temple_zz_inline_role_entry` (pri 51) only matches Discord `<@&ID>` mentions, not plain `@Momentum`/`@Swing` text.
- **Fix**: New `temple_zz_plain_entry` format (pri 50) — regex `^SYMBOL in [again/back/small] at PRICE [@Tag]`. Correctly captures symbol from start of line, handles optional `@Swing`/`@Momentum` text tags.
- **Files**: `src/signals/temple_parser.py` (new regex + parser), `src/services/signal_format_registry.py` (new registration + import)
- **Tests**: 66/66 existing tests pass, all 3 missed signals now correctly parsed.
- Only SNGX was detected today (BTO via range entry → conditional order → executed). SNGX STC also executed (breakeven close).

## Session: May 25, 2026 — Infra Trade Parser + Architect Gap Fixes

### FEATURE: Infra Trade / Small Account channel parser (signal_format_registry.py)
- **3 new formats**: `infra_trade_buy` (pri 12), `infra_trade_sell` (pri 13), `infra_trade_sell_symbol_only` (pri 72)
- **BUY**: Matches `**SMALL ACCOUNT :**` / `**SMALL :**` prefix with symbol/strike/opt_type/price. Extracts qty from `(N Calls/Puts)` or `(Total: N Calls)`. Extracts expiry from `Exp: MM/DD/YYYY` or `Exp; MM/DD/YYYY`. Defaults to 0DTE (today) when no Exp: found.
- **SELL with strike**: Matches `Sold [qty/all] SYMBOL STRIKEC/P at PRICE`. Supports qty, full_exit flag.
- **SELL symbol-only**: Matches `Sold [all/qty] SYMBOL [calls/puts] at/around PRICE`. Falls back when no strike info.
- **20/20 test signals pass** including all user-provided examples.

### Architect Review: 3 Critical Gaps Fixed
1. **GAP: `float(None)` crash in STC pre-check and broker matching** — `signal.get('strike', 0)` returns `None` (not `0`) when key exists with value `None`. Fixed: changed to `float(signal.get('strike') or 0)` and `(signal.get('opt_type') or '').upper()` at both STC pre-check (line ~15331) and broker position matching (line ~17555).
2. **GAP: STC missing expiry/strike/opt_type backfill** — When STC matches a position, `option_id` and `expiry_full` were copied back but NOT `expiry`, `strike`, or `opt_type`. Signal with `None` expiry would crash all brokers (`'/' in None` → TypeError). Fixed: added backfill of `expiry`, `strike`, `opt_type` from matched position at both broker-level match (line ~17620) and STC pre-check (line ~15430).
3. **GAP: STC matching required exact strike/opt_type** — `sell_symbol_only` with `strike=None` would fail `abs(p_strike - 0) < 0.01` for any non-zero strike. Fixed: skip strike/opt_type matching when signal has None values (match by symbol only).
4. **GAP: Webull 3-part expiry year extraction** — `expiry_mmdd.split('/')` only used first 2 parts, ignoring year in `MM/DD/YYYY`. Fixed at Webull `_blocking_place` to extract year from 3-part dates.

## Session: May 25, 2026 — Dashboard Close Position Fix (OrderResult.fill_price)

### BUG: Manual close from Dashboard fails for IBKR/Schwab/Tastytrade
- **Problem**: Trading → Dashboard → Live Trading Monitor → close position gives: `IBKR close error: 'OrderResult' Object has no attribute 'fill_price'`
- **Root cause**: `OrderResult` class in `src/broker_interface.py` has attribute `price`, not `fill_price`. Four locations in `gui_app/routes.py` accessed `result.fill_price` — all crash with `AttributeError`.
- **Affected brokers**: Schwab (line 6742), IBKR (line 6787), Tastytrade (line 6832), and Close-All endpoint (line 7842)
- **Fix**: Changed `result.fill_price` to `result.price` at all 4 locations
- **Note**: Alpaca and Robinhood use dict-style results (`result.get('fill_price')`), so they were not affected

## Session: May 22, 2026 — Customer Log Analysis + PT Rescaling + RGTI Sizing + UnboundLocalError Fixes

### Customer IBKR_LIVE Log Analysis (C:\VSCode\logs\bot.log)
- **Problem**: NIVF, VIDA, CODX, QUCY — no risk management despite phoenix channel having risk settings enabled
- **Root cause**: Position monitor's `start_monitoring()` async task crashes silently in user (PyArmor) build. Confirmed `_var_var_1232` UnboundLocalError — PyArmor obfuscation issue. Zero monitoring cycles/heartbeats in 4+ hours of log.
- **Fix**: Added `add_done_callback` on risk task in `selfbot_webull.py:8818` to catch silent crashes. Wrapped all init steps in `start_monitoring()` with individual try/except blocks so one failure doesn't kill the loop.

### QTEX PT Rescaling Bug (broker_sync_service.py)
- **Problem**: Range entry `QTEX 0.30-1.06` filled at $0.8166. Sync service recalculated PT from $1.06 to $2.8853 (253% above fill) using percentage-based rescaling designed for small slippage.
- **Root cause**: `pt_pct = (old_pt - intended) / intended` = `(1.06 - 0.30) / 0.30` = 253%. Applied to fill: `$0.8166 × 3.53 = $2.88`. The rescaling assumes fill≈intended, which fails for range entries where signal price is the low end.
- **Fix**: Added 50% divergence guard at all 3 recalculation sites in `broker_sync_service.py`. If fill price diverges >50% from signal price, skip rescaling entirely and log it.

### RGTI Position Sizing Bug — $2100 Instead of $21 (broker_health_monitor.py)
- **Problem**: RGTI stock signal ($21/share) rejected with "Insufficient settled cash: need $2100.00, have $376.59". Position sizing (25% of $376.59 = ~$94) never ran.
- **Root cause**: Health monitor `pre_trade_validation()` at line 666 uses `signal.get('asset_type', 'option')` but stock signals use key `'asset'` not `'asset_type'`. Missing key defaults to `'option'`, applying 100x multiplier: $21 × 100 = $2100. Trade rejected before position sizing code could run.
- **Fix**: Changed to `signal.get('asset_type') or signal.get('asset', 'option')` — checks both key names.

### `_phoenix_registry_extras` UnboundLocalError (selfbot_webull.py)
- **Problem**: `on_message` crashes with `UnboundLocalError: cannot access local variable '_phoenix_registry_extras'` during RGTI and QTEX processing on TEMP-BOOM channel.
- **Root cause**: Variable initialized at line 12295 inside `if should_convert:` block (16 spaces), but referenced at line 16680 in stock processing path (12 spaces). For channels with `execute_enabled=1` that aren't signal conversion channels, `should_convert` is False, skipping the initialization.
- **Fix**: Moved `_phoenix_registry_extras = []` to 8-space level before `if should_convert:` so it's always defined.

## Release: v10.2.1 — May 20, 2026
- **Commit**: `378b0563` pushed to `origin/main`
- **Admin build**: Triggered via `admin_release_ready` dispatch on `DiscordTrader/BotifyTradesv2`
- **User build**: Triggered via `user_release_ready` dispatch on `DiscordTrader/BotifyTradesv2` → publishes to `DiscordTrader/BotifyTrades`
- **Changes**: 21 files, 6241 insertions, 192 deletions
- **Highlights**: IBKR persistence hardening (3 fixes), Discord wake-from-sleep retry loop, conditional order stdout diagnostics, AI signal parser Claude integration, settings dropdown visibility fix

## Session: May 20, 2026 — IBKR Position Persistence Hardening (P0)

### BUG: IBKR positions vulnerable to false closure during reconnect storms
- **Reported**: User observed positions losing SL/PT/channel after restart, showing as "broker synced"
- **Root cause**: Three compounding vulnerabilities in `broker_sync_service.py`:
  1. **No `_fetch_error` for IBKR** — When IBKR disconnects, `get_positions_detailed()` returns `[]` and sync never set `_fetch_error = True`, so the fetch-error safety net at line 1375 never fired. Compare to Schwab which had explicit `_fetch_error` handling. Also, exception handler at line 750 printed error but didn't set the flag.
  2. **Broker-level empty guard too lenient** — `required_consecutive = 2` with `required_time_seconds = 0`. During IBKR reconnect storms (78 cycles in logs), just 2 consecutive empties (~1 min) allowed trade closures to proceed.
  3. **Per-trade guard too low** — `_REQUIRED_CONFIRMATIONS = 3` meant only 5 total empty cycles (~2.5 min) could falsely close a real DB trade.
- **Kill chain**: IBKR disconnects → returns `[]` (no error flag) → 2 broker empties pass broker guard → 3 more empties pass per-trade guard → DB trade closed → on reconnect position reappears but `auto_import_external=false` blocks reimport → orphaned position with no SL/PT/channel.
- **Fixes applied to `src/services/broker_sync_service.py`**:
  1. Set `result['_fetch_error'] = True` when IBKR is disconnected (line 753-755) AND when fetch throws exception (line 752)
  2. Broker-level guard: IBKR now requires 6 consecutive empties + 120s elapsed (was 2/0s). Other brokers raised to 3/30s.
  3. Per-trade guard: IBKR now requires 8 confirmations (was 3). Other brokers raised to 4.
- **Protection math**: IBKR now needs 6+8=14 consecutive empty cycles (~7 min at 30s interval) AND 120s elapsed before closing a trade. But with `_fetch_error` set on disconnect, the counter never even starts — empties during disconnect are completely blocked.

### BUG: Discord disconnects on auto-start after computer wake from sleep
- **Reported**: User has bot set to auto-start when computer wakes. Discord always disconnects. Manual stop+start fixes it.
- **Root cause**: `discord_main()` in `selfbot_webull.py:21278` had a single-shot connection attempt with NO retry. When computer wakes from sleep, network interfaces aren't ready yet. `client.start(USER_TOKEN)` fails immediately (DNS/TCP timeout). The exception handler enters fallback mode (brokers only, no Discord) and never retries.
- **Why manual restart works**: By the time user opens GUI and clicks Stop/Start, network is fully up → single attempt succeeds.
- **Fix**: Replaced single-shot `await client.start()` with a retry loop:
  1. **Network readiness check** — probes `discord.com:443` and `1.1.1.1:443` before attempting. If down, polls every 5s for up to 60s.
  2. **5 retry attempts** with increasing delays (10s, 15s, 20s, 30s, 45s) — total ~2 min window for network to come up.
  3. Token errors (no token configured) break immediately — no pointless retries.
  4. Fresh `SelfClient()` on each retry to avoid stale state.
  5. Existing fallback mode preserved: if all 5 retries fail, brokers still initialize without Discord.
- **Files**: `src/selfbot_webull.py` (lines 21278-21380)

### BUG: Conditional orders fail silently for all channels — 100% failure rate
- **User**: Running v10.1.1, Schwab broker, 6 conditional order signals (GOVX, VRAX, CISS, AIIO, SBFM) — ALL failed
- **Log pattern**: `[CONDITIONAL] ✓ Detected conditional order: GOVX over $3.8` → `[CONDITIONAL] ⚠️ Failed to create conditional order [SCHWAB]` — no error detail
- **Root cause analysis**: `base.py:create_order()` returns `None` before reaching DB INSERT. All early-exit checks log to stderr only (via `self._log()` → `sys.stderr.write()`), making them invisible in user's log file.
- **Probable cause**: One of: (a) `conditional_order_enabled=0` on channel, (b) DB schema mismatch in v10.1.1 vs current INSERT columns, (c) `is_enabled()` returning False
- **Fix**: Added `print()` (stdout) diagnostics to ALL early-exit checks in `base.py:create_order()` — service disabled, trading paused, execute OFF, conditional disabled, no broker. Also added try/except around the DB INSERT call with stdout traceback. Next user log will show exact blocker.
- **Files**: `src/services/conditional_orders/base.py` (lines 1504-1548, 1737-1784)
- **Secondary finding**: ProTrader channel (PIII) has `execute_enabled=0` — this is expected/correct behavior

## Session: May 20, 2026 — IBKR Close Position Bug Fix (P0)

### BUG: IBKR positions cannot be closed from Dashboard — "cannot access local variable 'asyncio'"
- **Reported**: User screenshot confirmed browser alert: `IBKR close error: cannot access local variable 'asyncio' where it is not associated with a value`
- **Root cause**: Python scoping bug in `close_position_by_id()` (routes.py line 6778). A conditional `import asyncio` at line 6523 (inside bracket cleanup `if` block) caused Python's compiler to treat `asyncio` as a local variable for the entire function. When the IBKR sell code at line 6778 ran, the conditional import hadn't executed yet → `UnboundLocalError`.
- **Fix**: Added `import asyncio` at function top (line 6399), alongside existing `import concurrent.futures`. The later conditional import is now redundant but harmless.
- **Additional fix**: Added `isConnected()` guard to `ibkr_broker.place_stock_order()` and `place_option_order()` — previously these methods had no connection check, so during the IBKR reconnect storm they would throw cryptic errors instead of a clear "not connected" message.
- **Secondary issue found**: IBKR WebSocket in reconnect death loop — 78 timeouts, 73 failed reconnects, 75 successful reconnects in ~1 hour. Connection recovers but never receives streaming data → times out every 30s. This is a TWS/Gateway-side issue (market data subscription or TWS state).
- **PIII position**: 2 shares @ $8.20 entry, running +13.3% ($9.29) with NO SL/PT set. Risk engine monitors but never auto-exits.
- **Files**: `gui_app/routes.py` (line 6399), `src/brokers/ibkr_broker.py` (lines 468, 551)

## Session: May 18, 2026 — Multi-Plan Execution + Claude AI Integration

### Multi-Plan Message Fix (GOVX + CISS)
- **Problem**: When ZZ Boom sends two plans in one message (`$GOVX\n...\n\n$CISS\n...`), only the first was detected
- **Fix**: Added `parse_all()` method to SignalFormatRegistry that splits on `\n\n+(?=\$[A-Z])` boundaries
- **Execution**: Added multi-plan processing loop at end of stock signal pipeline — each extra gets BTO guard, channel config copy, DB save, and queue
- **Files**: `signal_format_registry.py` (parse_all), `selfbot_webull.py` (extras loop at ~line 16522)

### Claude AI Integration (Anthropic API)
- **Architect review**: Safety review doc at `docs/claude_ai_integration_review.md`
- **Provider added**: `claude` option in Settings > AI & Market Data APIs dropdown
- **Components updated**:
  - `config_service.py` — added `'claude'` to AI_PROVIDERS
  - `broker_credentials_service.py` — added `anthropic` key to api_keys_extended (with default migration)
  - `ai_signal_parser.py` — added `_init_anthropic_client()` and `_call_anthropic()` methods, provider-based routing
  - `format_trainer.py` — added Claude client init and dispatch in learn/parse methods
  - `settings.html` — Claude dropdown option, Anthropic API key field, JS save/load/show-hide
  - `routes.py` — all 5 `save_api_keys_extended` callers updated to preserve `anthropic` key
  - `requirements.txt` — added `anthropic>=0.30.0`
- **Safety**: Zero changes to `signal_parsing_pipeline.py`. All existing gates intact:
  - AI disabled by default (`_ai_enabled=False`)
  - AI execution blocked (`_ai_execution_allowed=False`)
  - Admin approval required (`admin_approved=False` hardcoded)
  - Confidence threshold 0.8
- **Model**: Claude Haiku 3.5 (fast, cheap, excellent at structured extraction)
- **Verified**: All safety gate tests pass, integration tests pass

## Session: May 14, 2026 — Temple of Boom (ZZ) Parser: 2 Bugs Fixed

### BUG 1: OCG missed — structured entry parser required ❌ stop loss line
- **Root cause**: `temple_zz_structured_entry` regex required `❌ PRICE` line. OCG signal had no SL: `$OCG ✅ 2.25 🎯 5% 10% 15%`
- **Fix**: Made ❌ line optional via `(?:❌...)?` in regex. Parser returns `stop_loss_value=None` when absent — channel risk settings provide SL as fallback
- **Bonus**: Also fixed percentage target parsing. `🎯 5% 10% 15%` now converts to dollar targets using entry price (was silently discarding % targets)
- **Files**: `src/signals/temple_parser.py` (regex + `_parse_zz_targets` + `parse_temple_zz_structured_entry`), `src/services/signal_format_registry.py` (pattern update)

### BUG 2: Performance updates triggering duplicate BTO orders
- **Root cause**: `temple_zz_range_entry` pattern (`SYMBOL LOW-HIGH`) matched both new entries and performance updates (`AIIO 1.45-1.88🔥` = "went from 1.45 to 1.88"). Result: AIIO bought 4x (1 legitimate + 3 duplicates), YMAT 2x, QUCY 1 extra
- **Fix**: Added position-aware BTO duplicate guard in `selfbot_webull.py` at both LIVE and PAPER execution paths. Before queuing any stock BTO, checks trades DB for existing OPEN/PENDING trade with same (symbol, channel_id). If found → blocked with `[BTO GUARD] ⛔ BLOCKED duplicate BTO`
- **Defense-in-depth**: Guard catches ALL duplicate BTOs from any parser, not just range_entry — protects against future pattern ambiguities too
- **File**: `src/selfbot_webull.py` (2 insertion points: live execution path + paper trading path)
- **Tests**: 154/154 temple parser tests pass

---

## Session: May 13, 2026 — QUCY SL Bug: Architect Review & Fix

### BUG: Schwab SL triggered at 13.3% instead of configured 10% (QUCY)
- **Root cause**: SL price calculated from conditional order's `trigger_price` ($0.82) instead of actual `fill_price` ($0.8344). This widened effective SL from 10% to 11.6%, which combined with penny stock price gap, triggered at -13.3%.
- **Pipeline gap**: Signal builder in `selfbot_webull.py` computes SL/PT dollar prices using `triggered_price` (the only price available before fill). These wrong prices flow into the trades DB and position cache.

### Fix 1: `position_monitor.py` — `_reconcile_conditional_orders` (applied)
- Changed SL/PT recalculation in reconciliation to use `executed_price` from trades DB instead of conditional order's `trigger_price`
- Queries `executed_price` alongside symbol/broker in the open trades lookup
- Uses `base_price = fill_price if fill_price > 0 else trigger_price` for all SL/PT calculations

### Fix 2: `broker_sync_service.py` — Post-fill SL/PT recalculation (applied)
- Added recalculation block at all 3 PENDING → OPEN transition points:
  1. Main position-match fill (line ~1465)
  2. Schwab re-verify fill (line ~1779)
  3. Manual trades import promotion (line ~2851)
- When `fill_price != intended_price` (trigger price), back-derives the SL/PT percentage from the original values and recomputes using actual fill price
- Formula: `sl_pct = (intended - old_sl) / intended`, then `new_sl = fill_price * (1 - sl_pct)`
- Updates trade record in DB immediately after fill confirmation
- **Files**: `src/services/broker_sync_service.py`, `src/risk/position_monitor.py`

---

## Session: May 13, 2026 — Customer Bug: Trailing Stop Sells Full Position Before PT1

### BUG: Trailing stop activates AND triggers on same tick — sells 100% instead of PT1 partial (80%)
- **Customer report**: TDIC 15 shares, PT1=10% (sell 80%), but entire position sold. User expected 12 shares sold at PT1, 3 remaining.
- **Symptom**: `SELL 15 TDIC @ $3.88` — all 15 shares sold. Stock then rallied to $4.29 (+20.8%).
- **Root cause**: Exit was NOT PT1 — it was a **trailing stop** (full position exit). Three factors:
  1. **Config gap**: Trail activation (8%) < PT1 (10%). Trail always activates before PT1 can fire a partial exit.
  2. **Price spike**: TDIC jumped from $3.74 to $3.90 in 3 seconds. `interval_low` = $3.75 (pre-spike), `highest_price` updated to $3.90 (spike).
  3. **Same-tick activation + trigger bug**: Trail activated at +9.86% (>8% threshold), computed trail stop = $3.90 × 0.98 = $3.82, then `effective_low` ($3.75 from interval_low) <= $3.82 → triggered immediately. The interval_low predated the new high, creating a temporal mismatch.
- **Why PT1 didn't fire**: Price was +9.86%, PT1 threshold was 10.0% — **0.14% short**. PT evaluation uses `current_price` (not `interval_high`), so brief spikes above PT1 threshold are missed.
- **Fix**: Added `_just_activated` guard in `risk_engine.py` trailing stop evaluation. When trailing stop activates on a tick, it skips the trigger check on that same tick — prevents interval_low (from before the high was set) from immediately triggering the exit.
- **File**: `src/risk/risk_engine.py` (lines 639-668, step 6 "Legacy Trailing Stop")
- **User guidance**: Trail activation should be >= PT1 threshold to allow partial exits before trail takes over.

---

## Session: May 12, 2026 — Trade Monitor Multi-Broker Fix

### Trade Monitor was single-broker (Webull only) — now multi-broker
- **Symptom**: Trade Monitor Settings page configures fill detection + Discord webhook posting, but only Webull (unofficial) was monitored. Schwab, IBKR, Tastytrade, Alpaca, Webull Official, Robinhood fills were never posted.
- **Root cause**: `trade_monitor.set_broker(self.broker)` at startup hardcoded to `self.broker` = WebullBroker. The entire TradeMonitor class was single-broker architecture.
- **Fix**: Added `set_broker_manager()`, `_get_brokers_to_monitor()`, and `_fetch_filled_orders()` with per-broker normalization for all 7 US brokers. `_check_for_new_orders()` now iterates all connected brokers.
- **Files**: `gui_app/trade_monitor.py`, `src/selfbot_webull.py` (startup wiring)

### `_sync_filled_orders` missing Webull Official + Robinhood handlers
- **Symptom**: Broker Sync Service synced positions for these brokers but NOT filled orders — no fill propagation to execution_lots/lot_closures.
- **Fix**: Added filled order handlers using `get_order_history()` (Webull Official) and `get_orders('closed')` (Robinhood) with proper normalization. Also added Webull Official pending orders sync in `_fetch_and_normalize`.
- **File**: `src/services/broker_sync_service.py`

### `is_recent_fill` window too tight (10s → dynamic)
- **Symptom**: Fill detection window was hardcoded to 10 seconds. With 5-10s poll intervals + network latency, fills silently dropped.
- **Fix**: Changed to `max(poll_interval * 3, 30)` — 30s minimum, scales with poll interval.
- **File**: `gui_app/trade_monitor.py`

---

## Session: May 12, 2026 — ERNA Bot Log Investigation (v10.2.0)

### BUG #1 (CRITICAL): Trailing stop never activates when OCO bracket active
- **Symptom**: ERNA at +15.64% gain (above 11% activation threshold) but trailing stop permanently shows "Ready to activate" and never transitions
- **Root cause**: In `position_monitor.py:4476-4478`, when `evaluate_tiered_targets()` detects T1 PT hit AND an OCO bracket manages that tier, it returns `ExitDecision.no_exit()` immediately. This early return SKIPS the trailing stop evaluation at line 4544 entirely. The trail never gets evaluated, never activates, never exits.
- **Fix**: Changed OCO case to fall through (print message but don't return) so trailing stop + enhanced risk features still evaluate after OCO suppresses the PT sell.
- **File**: `src/risk/position_monitor.py` (line 4481-4482)

### BUG #2: Dashboard manual close fails for IBKR LIVE
- **Symptom**: User tried to close ERNA from Dashboard manually — failed silently
- **Root cause**: In `routes.py:6772`, the IBKR close path created `asyncio.new_event_loop()` — completely isolated from the bot's TWS WebSocket connection. IBKR's ib_insync is bound to the bot's event loop; calling it from a new loop fails. The dedicated IBKR endpoint at line 4566 correctly used `run_coroutine_threadsafe(... _bot_instance.loop)`.
- **Fix**: Replaced isolated loop with `asyncio.run_coroutine_threadsafe(..., _bot_instance.loop)` matching the dedicated endpoint pattern. Also fixed same issue for Tastytrade close.
- **File**: `gui_app/routes.py` (lines 6771-6782)

### BUG #3: ORDER_CHASER can't resolve IBKR_LIVE broker
- **Symptom**: `[ORDER_CHASER] ❌ Broker IBKR_LIVE not available` repeated in log
- **Root cause**: `_get_broker()` broker map had `ibkr_live` (lowercase) but broker_id comes as `IBKR_LIVE` (uppercase). Fallback attr name `ibkr_live_broker` doesn't exist on broker_manager.
- **Fix**: Added `'IBKR_LIVE': 'ibkr_broker'` to the broker map.
- **File**: `src/services/unfilled_order_chaser.py` (line 2168)

### DISPLAY FIX: SL=— in broadcast for percentage-based SL
- **Symptom**: `[RISK] 📡 ERNA $14.14 (+15.6%) | entry=$12.23 | SL=— PT=—` despite channel having SL=10%
- **Root cause**: Broadcast only checked `stop_loss_price` (dollar-value), but channel uses percentage-based SL.
- **Fix**: Computes SL dollar price from entry * (1 - sl_pct/100) when no dollar-value SL is set.
- **File**: `src/risk/position_monitor.py` (line 2778)

### BUG #4: Dashboard shows stale IBKR prices — TWO root causes
- **Symptom**: ERNA price frozen on Dashboard despite risk engine seeing live prices every second
- **Root cause A — IBKR broker returns 0 for current_price**: `get_positions_detailed()` in `ibkr_broker.py:404-415` gets prices from `self.ib.tickers()`, which requires explicit `reqMktData()` subscriptions. Most IBKR symbols only have `updatePortfolio` callbacks (sporadic). When `tickers()` returns no match, `current_price=0`, SYNC skips writing it to DB, and Dashboard reads stale DB value.
- **Fix A**: Added `self.ib.portfolio()` fallback — `portfolio()` returns `marketPrice` from TWS callbacks. When `tickers()` returns 0, use `portfolio_prices[conId]`.
- **File**: `src/brokers/ibkr_broker.py` (lines 393-416)
- **Root cause B — Streaming quotes endpoint ignores IBKR hub**: `/api/streaming/quotes` in `routes.py` only checked Webull and Schwab data hubs for 1-second streaming overlay. IBKR positions fell through to cross-broker lookup only.
- **Fix B**: Added IBKR data hub to streaming quotes — direct lookup for IBKR positions + cross-broker fallback for others. Added `ibkr` to streaming_status response and Dashboard indicator.
- **Files**: `gui_app/routes.py` (lines 7619-7670, 7715-7718), `gui_app/templates/index.html` (streaming indicator)

### BUG #5: AVG SPEED in PNL Tracker showing ~1423.6s instead of real execution speed
- **Symptom**: PNL Tracker "AVG SPEED" KPI shows 1423.6s — should be sub-second bot reaction time
- **Root cause**: `broker_sync_service.py:3796-3801` computed `latency_total_ms = signal_detected → order_filled` (includes broker queue + market fill delay, potentially hours). This overwrote the correct `signal_detected → order_submitted` value saved by `selfbot_webull.py` at order time. When `_compute_exec_speed()` fell back to `latency_total_ms` for rows missing timestamps, it returned inflated values.
- **Fix 1**: Changed `broker_sync_service.py` to compute `latency_total_ms = detected → submitted` (same as selfbot_webull.py). Also used COALESCE on UPDATE to prevent overwriting good values with NULL.
- **Fix 2**: Added 30s sanity cap in `_compute_exec_speed()` — bot reaction time >30s is corrupted data, excluded from average. Returns `None` instead of inflated values.
- **Files**: `src/services/broker_sync_service.py` (lines 3796-3803, 3836-3846), `gui_app/routes.py` (lines 12868-12891)

### ERNA Qty Mismatch (not a bug — multi-trade position)
- DB shows qty=16 across multiple trades, but IBKR portfolio shows qty=3 — previous partial fills/closes reduced the broker position. SYNC correctly skips qty sync for multi-trade positions. This is expected behavior.

---

## Session: May 12, 2026 (cont.) — Root Cause Found & Fixed: Schwab PNL Accuracy (v10.2.0)

### ROOT CAUSE #1: lot_id lost through conditional order path
- **Symptom**: `pending_order_metadata.signal_lot_id` is NULL for all Schwab trades from channels with entry confirmation enabled (e.g., phoenix/ERNA). MEHA worked because its channel had no entry confirmation.
- **Root cause**: When entry confirmation is enabled, `_save_signal_to_db(stk)` creates the lot and sets `stk['lot_id']`, but the code immediately creates a conditional order and `return`s — `stk` never reaches the order queue. When the conditional order fires later, `execute_conditional_order()` builds a NEW signal dict from scratch (line 10662) that has NO `lot_id`. This new signal goes via telegram bridge → worker → `save_pending_order_metadata(signal_lot_id=None)`.
- **Fix**: Added lot_id recovery in `execute_conditional_order()` — queries `signal_lots` by symbol + channel to recover the lot_id before queuing the fired signal.
- **File**: `src/selfbot_webull.py` (after line 11058)

### ROOT CAUSE #2: channel_id mismatch breaks fill propagation
- **Symptom**: `lot_closures.exit_fill_price` is NULL for ALL recent Schwab closures. `process_filled_order_event()` silently returned 0 matches.
- **Root cause**: `pending_order_metadata.channel_id` stores Discord channel IDs (e.g., `1293555678111072347`), but `signal_lots.channel_id` stores DB internal IDs (e.g., `2`). The query `WHERE sl.channel_id = ?` using the Discord ID never matches.
- **Fix**: Added Discord→DB channel_id resolution at the top of `process_filled_order_event()`. All signal_lots queries now use `db_channel_id` instead of the raw Discord `channel_id`.
- **File**: `gui_app/database.py` (lines 5202-5215, 5242-5245, 5299)

### Data Repair: `repair_pnl_data()` function
- New function in `gui_app/database.py` that fixes three categories of broken data:
  1. `lot_closures.exit_fill_price` NULL → backfills from STC trades (matched by trade_id + closure order)
  2. `pending_order_metadata.signal_lot_id` NULL → backfills from signal_lots (matched by symbol + channel + time proximity)
  3. STC trades with `executed_price=0` → backfills from lot_closures or filled_orders
- First run repaired **61 records**: 16 closures, 43 metadata, 2 zero-price trades
- Runs automatically on startup (idempotent)

### Previous fixes in this session (earlier context)

#### Bot Trades PNL priority fix
- **Root cause**: `get_bot_trades()` processed STC trades FIRST, then lot_closures for remaining qty. STC trade with `executed_price=0.0` consumed all qty with wrong PNL, so correct lot_closures were skipped.
- **Fix**: Flipped priority — lot_closures processed FIRST, STC trades only fill gaps.
- **File**: `gui_app/database.py` — `get_bot_trades()`

#### Speed column in PNL Tracker
- **Fix 1**: Create `execution_lots` immediately at BTO order placement with signal timestamps.
- **Fix 2**: Speed metric changed to signal_detected → order_submitted (bot reaction time).
- **Files**: `gui_app/routes.py`, `src/selfbot_webull.py`, `src/services/broker_sync_service.py`

## Session: May 11, 2026 — IBKR Risk Engine SL/PT Not Applied (Root Cause: TWS TIF Auto-Adjustment)

### Bug: Risk Engine Skips IBKR Positions as "External" — SL/PT Never Applied
- **Symptom**: Signal `BTO WOK @ 1.8, SL=1.66, PT=1.94` placed on IBKR. Order filled at $1.80, price reached $2.11 (+16%) — PT at $1.94 never triggered. Every tick showed `SL=— PT=—`. Log: `⏭️ Skipping external position IBKR_LIVE_WOK_stock — auto-import disabled`
- **Root cause (PRIMARY)**: TWS auto-adjusted TIF to DAY (error 10349), causing a transient `Cancelled→Submitted` status within ~1s. `_wait_for_fill()` treated `Cancelled` as final and returned immediately. `place_stock_order()` checked status='Cancelled' and returned `OrderResult(success=False)`. **Trade was never saved to DB.** Risk engine found no matching trade → classified as "external" → SL/PT skipped.
- **Root cause (SECONDARY)**: `get_open_trade_id_for_position()` normalized position broker `IBKR_LIVE` → `IBKR` for DB lookup, but trades could be stored as `IBKR_LIVE` (from multi-broker execution). The SQL `LOWER(broker) = LOWER('IBKR')` wouldn't match `IBKR_LIVE` in the DB.
- **Fix 1**: `ibkr_broker.py` — `_wait_for_fill()`: When `Cancelled` status received, wait 3 additional seconds for TWS resubmission before treating as final. Also `place_stock_order()` and `place_option_order()`: After initial Cancelled check, sleep 2s and re-check status (defense-in-depth).
- **Fix 2**: `position_monitor.py` — `get_open_trade_id_for_position()`: Added `brokers_to_check` list that includes both normalized name (`IBKR`) and original position broker (`IBKR_LIVE`). All stock and option trade lookup queries now iterate over broker variants.
- **Files changed**: `src/brokers/ibkr_broker.py` (3 methods), `src/risk/position_monitor.py` (4 query blocks in `get_open_trade_id_for_position`)
- **Log evidence**: bot.log lines 47397-47405 show PendingSubmit→Cancelled(10349)→Submitted→Filled sequence

### Penny Stock Scanner Tab (In Progress)
- New tab added to Trading→Trades with Webull real-time discovery
- 7 scan presets: Active, Gainers, Losers, Pre-Mkt Gainers/Losers, AH Gainers, Manual
- Files: `penny_scanner_service.py` (new), `routes.py` (4 endpoints), `trades.html` (~350 lines), `unified_price_hub.py` (open/close price propagation)

## Session: May 10, 2026 — AEHL Stop Loss Price Truncation Bug Fix

### Bug: AEHL SL Sent $1.00 Instead of $1.008
- **Symptom**: AEHL entry $1.12, SL 10%, expected SL price $1.008 → bot sent SELL LIMIT $1.00 GTC, filled $1.0201
- **Root cause**: `_format_price()` in schwab_broker.py used `math.floor` with 2-decimal precision for ALL prices >= $1.00. For $1.008: `floor(1.008 * 100) / 100 = 1.00` — lost almost a full cent
- **Fix**: Changed `_format_price()` from `floor` to `round` for prices >= $1.00. SEC Rule 612 requires penny increments for NMS stocks above $1; sub-penny (4-decimal) only valid for OTC stocks under $1.
- **Architect review**: Initial fix used 4-decimal sub-penny for all stocks under $5 — rejected because Schwab/exchanges would reject sub-penny prices for NMS stocks above $1. Revised to `round(price, 2)` which properly snaps to nearest cent.
- **`_stock_tick_below()`**: Unchanged — already correct at $1.00 boundary (sub-$1 stocks get 0.0001 tick, $1+ stocks get 0.01 tick)
- **Files changed**: `src/brokers/schwab_broker.py` — `_format_price()` (line 589)
- **Verification**: $1.008 now formats as `"1.01"` (was `"1.00"`). All 539 tests pass.

### Architect Review: Cross-Broker Price Formatting Audit
Reviewed all 6 active brokers for the same `floor()` / sub-penny truncation bug:

| Broker | How Price Sent | Penny Stock Handling | Bug? | Fix |
|--------|---------------|---------------------|------|-----|
| **Schwab** | `_format_price()` → string | Was `floor()` for all ≥$1 | **YES** | Changed to `round(price, 2)` |
| **Webull Legacy** | `float(price)` → SDK | `round(bid*0.97, 2)` for all prices | **YES** | Added `_rd = 4 if price < 1.0 else 2` to 8 rounding sites |
| **Alpaca** | SDK `round(price, 4 if <1 else 2)` | Already correct | No | — |
| **IBKR** | `LimitOrder(side, qty, float)` → TWS | TWS API handles rounding | No | — |
| **Tastytrade** | `Decimal(str(price))` → SDK | Full precision preserved | No | — |
| **Robinhood** | `float(price)` → robin_stocks SDK | SDK handles formatting | No | — |
| **Webull Official** | `str(float)` → v2 API | API handles rounding | No | — |

**Webull Legacy fix details**: Aggressive exit paths (`round(bid * 0.97, 2)`) used 2 decimals for ALL stocks. For extreme pennies ($0.0045), this rounded to $0.00 — then `max(0.01, ...)` caught it but set price 122% above bid. Fixed 8 rounding sites to use 4 decimals when price < $1.00. Also fixed extended-hours MKT→LMT conversion (was hardcoded 4 decimals for all prices).

### Bug: IBKR Risk Engine Skipping All Positions (Broker Name Mismatch)
- **Symptom**: All IBKR positions logged as "⏭️ Skipping external position" — no SL/PT applied. MASK dropped -8.1% with 10% SL configured but never triggered.
- **Root cause**: Position snapshots use `IBKR_LIVE`/`IBKR_PAPER` labels (position_monitor.py:3293), but trade DB stores `IBKR` (selfbot_webull.py:19577). DB lookup `LOWER(broker) = LOWER('IBKR_LIVE')` never matches `'ibkr'` → trade_id=None → position treated as external → risk engine skips it.
- **Scope**: Affects ALL brokers with live/paper suffixes: IBKR, Alpaca, Tastytrade, Trading212.
- **Fix**: 
  1. Added `db_broker` property to `PositionSnapshot` (risk_types.py) that strips `_LIVE`/`_PAPER` suffix via regex
  2. Normalized broker name in `get_open_trade_id_for_position()` and `get_channel_risk_settings()` (position_monitor.py)
  3. Updated 8 scattered DB query sites in position_monitor.py to use `position.db_broker` instead of `position.broker`
  4. Auto-import trade creation now stores normalized broker name
- **Files changed**: `src/risk/risk_types.py`, `src/risk/position_monitor.py`

### Bug: IBKR Sub-Penny Price Rejection (Warning 110)
- **Symptom**: IBKR TWS rejected MASK conditional order at $3.1363 — "price does not conform to minimum price variation"
- **Root cause**: `ibkr_broker.py` passed raw float prices from conditional orders directly to `LimitOrder()`. Conditional order system computes prices with 4-decimal precision regardless of stock price.
- **Fix**: Added SEC Rule 612 price rounding in `ibkr_broker.py` — `round(price, 2)` for stocks >= $1.00, `round(price, 4)` for sub-$1 penny stocks. Applied to both stock (line 467) and option (line 551) order paths.
- **Files changed**: `src/brokers/ibkr_broker.py`

### Webull Official Full Cross-System Wiring (14 files)
- Wired Webull Official into every integration point: conditional order router (3 registration blocks), position_monitor (fetch + 5 dispatch blocks), broker_sync_service (discovery + fetch), execution pipeline (broker_override), unified_price_hub, broker_credentials_service, broker_live_analytics, routes.py, index.html, channels.html, channels.js, settings.html
- All dispatch chains place `WEBULL_OFFICIAL` BEFORE `WEBULL` to prevent false substring matches

### QA Playbook Update (v4.4.0 → v4.5.0)
- Added 26 Webull Official cross-system wiring test cases (17.52x–17.52aw) covering conditional order router, position monitor, broker sync, execution pipeline, UI templates, routes
- Added 11 broker name normalization (`db_broker`) test cases (17.64–17.74) covering the IBKR/Alpaca/Tastytrade/Trading212 mismatch fix
- Added 5 IBKR sub-penny price guard test cases (17.75–17.79) covering SEC Rule 612 rounding
- Total test cases: 625+ → 670+

### Architecture Note: Risk Engine Uses Software SL, Not Broker-Side STOP Orders
- The risk engine monitors prices in software and sends reactive SELL LIMIT orders when SL breaches
- `place_stop_order()` (broker-side STOP) exists in schwab_broker.py but is only used by the OCO/bracket system
- SL exits force `use_market=True` (position_monitor.py:7280-7283) → Schwab converts to aggressive LIMIT → `_format_price()` truncates

## Session: May 8-9, 2026 — Webull Official API Integration Design

### Deliverable: `docs/webull_official_api_design.md`
Complete architecture design for official Webull API integration (v2 REST API).

### Task 1: Documentation Review (15 categories)
- Auth: HMAC-SHA1 per-request signing (stateless, no token refresh needed)
- Full endpoint catalog: place/cancel/replace/batch orders, account balance, positions, order history
- Rate limits mapped: 600 req/min (orders), 2 req/2s (account data), 10 req/30s (auth)
- MQTT streaming: protobuf format, max 100 symbols, 5 connections per app key
- gRPC trade events: fill notifications, but grpcio doesn't build on Python 3.14
- Sandbox: UAT environment with 3 public test accounts available

### Task 2: Feature Mapping (30 features → exact endpoints)
- All 27+ BotifyTrades features mapped to specific Webull v2 API endpoints
- **Critical finding:** Options are supported via standard `/openapi/trade/order/place` with `instrument_type: "OPTION"` + `legs[]` — the SDK's separate HK-only `place_option()` methods are NOT needed
- **Major upgrade:** Native OCO/OTO/OTOCO bracket orders via `combo_type` field — replaces client-side bracket management
- Gap identified: No REST quote endpoint (quotes come from MQTT streaming only)

### Task 3: Architecture Design
- 13-file module under `src/brokers/webull_official/`
- Direct httpx HTTP client (NOT the outdated v1 SDK)
- Full BrokerInterface implementation with stock + option orders
- Native bracket order support (OTOCO with MASTER + STOP_PROFIT + STOP_LOSS)
- MQTT streaming client + trade event polling fallback
- Token bucket rate limiter per endpoint category
- Estimated: ~1,575 lines, ~14 days, 4-phase rollout

### Key Design Decisions
1. **Direct HTTP over SDK**: Installed SDK is old v1 API (HK-focused); v2 REST API uses `symbol` directly
2. **Native brackets**: OTOCO replaces client-side position_monitor brackets for Webull
3. **gRPC fallback**: Poll open orders every 3s instead of gRPC (Python 3.14 compat)
4. **client_order_id**: UUID hex, 32 chars, stored in position cache for cancel/replace

### QA Plan: `docs/webull_official_qa_plan.md`
- 4 QA gates (one per implementation phase), each with:
  - Automated pytest suite (~80 new tests across 4 test files)
  - Regression check (existing 423-test suite must pass unchanged)
  - Manual validation checklist (8-15 items per gate)
  - Gap report template with Go/No-Go criteria
- Gate 1: Core module (auth signing, config, rate limiter, models, exceptions)
- Gate 2: Trading operations (orders, accounts, positions, BrokerInterface contract)
- Gate 3: Bot integration (UPH, relay, GUI routes, signal routing, import safety)
- Gate 4: Streaming + final validation (MQTT, trade event polling, UAT smoke test)
- Total test count after all gates: ~503 (80 new + 423 existing)

## Session: May 6, 2026 — QA Playbook, Gap Fixes, Architecture Page Redesign

### QA Playbook (7-Point)
Ran comprehensive QA across all 6 temple_zz parsers and bracket fill bridge. Found 2 actionable gaps:

### Gap A Fix: "break of" variant
- **Problem**: `"MASK break of 1.80 takes it to 2.00"` failed — regex didn't handle "break of"
- **Fix**: Added `(?:of\s+)?` after `break(?:s)?` in `TEMPLE_ZZ_BREAKOUT` pattern (`temple_parser.py`)
- **Registry**: Updated pattern + added example in `signal_format_registry.py`

### Gap B Fix: Price-first with symbol at end
- **Problem**: `"2.50 must break for 2.71 OCG"` — price-first, ticker-last format not parsed
- **Fix**: New `TEMPLE_ZZ_BREAKOUT_REVERSE` regex + `parse_temple_zz_breakout_reverse()` function
- Handles: `"21.50 break takes it to 25 AVTX"`, `"3.80 break only for 4.43 WAI"`, `"has to break"` / `"must break"` variants
- Registered at priority 74 in format registry

### Range Entry Emoji Fix
- `"CRE 2.80-3.91🔥"` and Discord custom emoji variants now match via `[^\x00-\x7F]` alternative

### QA Results
- 17/17 edge cases pass, 0 false positives, 0 cross-pattern collisions
- Real message coverage: 13 → 17 matches (+31%) from trading-floor export
- Total registered formats: 109

### Architecture Page Redesign
- Backup saved to `gui_app/templates/architecture_backup.html`
- Complete rewrite of `architecture.html` (1197 lines) — industry-grade professional layout
- New sections: "How It Works" 4-step flow, 10 feature cards, Risk Architecture deep-dive, 12 capabilities
- Enhanced hero: "Execute Smarter. Trade Faster." + 5 trust metrics
- Professional 4-column footer with 5-paragraph legal disclaimer (not financial advice, no signal recommendations, trading risk, user responsibility)
- Aurora dark theme preserved with glassmorphism, animated SVG logo, particles

## Session: May 6, 2026 — OCO Bracket Fill → Risk Tier Bridge (CRITICAL)

### Problem
When bracket orders (OCO) are enabled, broker-side fills (PT hit or SL hit) were never fed back to the risk tier system. This caused:
- No PT cascade (PT2/PT3/PT4 never placed after PT1 fills at broker)
- No dynamic SL escalation (SL doesn't move to breakeven after PT1)
- Double-sell risk (risk monitor doesn't know broker already sold shares)

### Architecture: 4-Layer Fix

**Layer 1 — Runtime Detection** (`position_monitor.py`):
- New `_detect_and_handle_bracket_fill()` — rate-limited (15s/position), queries OCO status, determines PT vs SL, marks tier via `mark_tier_hit`, escalates dynamic SL, cascades next PT bracket via `_enqueue_broker_op`
- New `_clear_bracket_state()` helper
- Call site integrated before stale bracket reset, guards reset if fill was handled

**Layer 2 — Enriched API** (`schwab_broker.py`):
- `get_order_status()` now walks `childOrderStrategies` for OCO orders, returns `fill_leg` ('pt'/'sl'), `fill_leg_qty`, `fill_leg_price`

**Layer 3 — Sync Attribution** (`broker_sync_service.py`):
- `_sync_filled_orders()` matches STC fills against cached OCO PT/SL prices (3%/5% tolerance), marks tier and sets proper `exit_source`

**Layer 4 — Bracket Reconciliation** (`broker_sync_service.py`):
- All three reconciliation methods (`_reconcile_schwab_brackets`, `_reconcile_ibkr_brackets`, `_reconcile_generic_brackets`) now return enriched `'pt_filled'`/`'sl_filled'` instead of generic `'filled'`
- Caller `_reconcile_brackets` handles enriched results: marks tier on PT fill, logs SL fill

**Tier-Aware Initial Bracket** (`position_monitor.py`):
- `_place_initial_broker_bracket` finds first unhit tier instead of always targeting T1
- Uses escalated dynamic SL price when available
- Updated `broker_pt_tier` assignment across all 9 broker sections

### Architect Review — 7 Gaps Found and Fixed
After initial 4-layer implementation, architect review found 7 gaps in the bracket-only code path (zero software path changes):

| # | Severity | Gap | Fix |
|---|----------|-----|-----|
| 1 | CRITICAL | Orphaned standalone SL after OCO PT fill — `_clear_bracket_state` cleared ID without cancelling | Cancel standalone SL at broker before clearing state |
| 2 | CRITICAL | SL fill reset `broker_orders_placed=False` → fresh brackets on stopped-out position | Override to `True` after clearing to prevent re-placement |
| 3 | CRITICAL | Layer 1 ignored standalone SL-only fills (`sl_only`, `escalation_only`, options) | Added `broker_stop_order_id` as third check_type in priority chain |
| 4 | HIGH | Standalone PT fill: tier never marked (no fill_leg, no OCO prices for inference) | Infer `fill_leg='pt'` when `check_type='standalone_pt'` |
| 5 | HIGH | Layer 1 cleared OCO prices before Layer 3 sync attribution could use them | Preserve as `_last_bracket_pt_price`/`_last_bracket_sl_price` before clearing |
| 6 | MEDIUM | Layer 4 `pt_filled` on restart didn't escalate dynamic SL | Calculate + set `dynamic_sl_price` after `mark_tier_hit` in sync reconciliation |
| 7 | MEDIUM | Cascade used stale position snapshot (qty=0 after full exit) | Added `next_qty <= 0` guard after remaining_qty cap |

### Software-Only Path
Confirmed: when brackets are disabled, the existing software evaluation path (tiered_targets → risk_engine → position_monitor exits) remains fully intact and unaffected. All 7 fixes are contained within bracket detection, bracket state cleanup, and bracket cascade code.

## Session: May 5, 2026 — Schwab Sync Service Gap Fix

### Bug: Stale MNDR Position (trade #49)
- **Root cause**: Schwab was never included in the sync service's broker list. At startup, Schwab had no tokens (`is_authenticated()` returned False), so `self.schwab_broker = None`. Even after Schwab connected later (via hot-connect or OAuth callback), the sync service's BrokerManager copy wasn't always updated.
- **Evidence**: Bot log shows only `['Webull']` and `['Webull', 'IBKR_LIVE']` in sync cycles — never Schwab. No `[SCHWAB HOT-CONNECT]` log entries in session.
- **Impact**: The `broker_closed_position` detection (line 1853) never ran for Schwab trades, leaving MNDR stuck as OPEN forever.

### Fixes
1. **`broker_sync_service.py`** — `_perform_sync()` Schwab check now falls back to `_bot_instance.schwab_broker` when `broker_manager.schwab_broker` is None (catches hot-connect gap). Also syncs if `connected=True` even when `is_authenticated()=False`. Auth check errors now logged instead of silently swallowed.
2. **`schwab_auth.py`** — `_deferred_schwab_connect()` retry path now updates `bm.schwab_broker` on the sync service BrokerManager (was missing, only the bot instance was updated).
3. **Manual cleanup**: Closed trade #49 (MNDR, SCHWAB) in DB as `broker_closed_position`, removed `SCHWAB_MNDR_stock` from position cache.

## Session: May 4, 2026 — Trading Pause Gate, Restart DLL Fix, FOR Parser Fix (v9.3.6)

### Features
- **Trading pause early gate**: Added single check in `_process_message()` (selfbot_webull.py:11557) that blocks ALL Discord signal processing when trading is paused — parsing, conditional orders, execution. Uses 2s TTL cached DB check to avoid per-message DB hits. Defensive backup gate in `conditional_orders/base.py:create_order()`.
- **Risk monitoring interval**: Changed default from 1.0s to 0.2s (`position_monitor.py`)
- **UI cleanup**: Hidden Robinhood/Trading212 broker cards, hidden risk interval row in settings

### Fixes
- **Restart DLL race condition**: PyInstaller frozen builds failed with "Failed to load Python DLL" on restart because the batch script launched the new exe before Windows released `_MEI` temp folder file handles. Fixed with PID-polling batch script + 3-retry logic (`lifecycle_manager.py:246-275`). macOS/Linux delay increased to 4s.
- **FOR conditional order false positive**: Message "first target for ABVE 0.78" was parsed as `FOR above $0.78` because FOR matched as ticker and ABVE matched as typo for "above". Fixed by adding `'FOR'` to `english_stopwords` set in `parser.py:945`.

### Release
- v9.3.6 committed and pushed, CI builds triggered on both private (admin) and public (user) repos

### Trade Audit (May 4)
- 5 trades executed: NIVF (-$0.36), ABVE (+$4.99), FOR (-$0.24, false positive), CNSP (-$8.76), ELPW (+$1.30)
- All had OCO brackets placed and triggered correctly at Schwab
- Orphaned brackets cleaned up properly for FOR, ELPW, CNSP

## Session: May 3, 2026 — Bracket Order Restart Reconciliation (v9.3.5)

### Problem
- On bot restart with open positions that have active bracket orders (Schwab OCO, IBKR OCA, standalone SL/PT), the cache loader cleared all bracket IDs and set `broker_orders_placed=False`. The first eval cycle then placed **duplicate** SL/PT orders at the broker — old ones still WORKING + fresh ones = double-sell risk.

### Solution: Preserve-and-Reconcile Pattern
1. **risk_types.py** — Added `_bracket_needs_reconciliation` runtime flag (not persisted)
2. **position_cache.py** — Modified `load()` to preserve bracket IDs when they exist instead of clearing. Keeps `broker_orders_placed=True` to block duplicate placement before reconciliation
3. **broker_sync_service.py** — Added ~150-line reconciliation engine:
   - `reconcile_bracket_orders()` — runs once per position on first sync after restart
   - Broker-specific handlers: Schwab (OCO parent status), IBKR (individual SL/PT), generic (all other brokers)
   - 4 outcomes: RESTORED (orders still active), FILLED (triggered during downtime), CLEARED (gone → fresh placement), DEFERRED (broker unreachable → retry)
   - `_clear_bracket_ids()` helper resets all bracket fields
4. **ibkr_broker.py** — Added `oca_group` and `stop_price` fields to `get_pending_orders()` response

### Files Modified
- `src/risk/risk_types.py:335` — `_bracket_needs_reconciliation` flag
- `src/risk/position_cache.py:283-297` — Preserve bracket IDs on load
- `src/services/broker_sync_service.py:429,2940-3128` — Reconciliation hook + engine
- `src/brokers/ibkr_broker.py:244-256` — OCA group exposure

### Also This Session
- License BTF-key validation fix (3 bugs in `gui_app/routes.py`)
- Alertsify comparison doc update (score 82→89, gaps 8→3)
- Version bump to 9.3.5, released to both repos

## Session: April 29, 2026 — Cross-Platform Encoding Fix + License Validation Hardening

### Problem
- 16 test failures (7 fails + 9 errors) across `test_risk_engine.py` and `test_route_audit.py`
- Architect review found **65+ file I/O calls** missing `encoding='utf-8'` across the codebase
- On Windows (CP1252 default), any file with non-ASCII chars (emoji, special chars) would corrupt/crash
- License validation, token storage, trade data, and position caches all affected

### Root Causes
1. **test_risk_engine.py (5 fails)**: Tests had stale SL profile assertions — production code was intentionally tightened to `standard: BE/+5%/+10%/+17%` but tests still expected `BE/+5%/+15%/+25%`
2. **test_route_audit.py (11 errors/fails)**: `read_text()` without `encoding='utf-8'` — `routes.py` has emoji chars that CP1252 can't decode
3. **Systemic encoding gap**: 65+ `open()` and `read_text()/write_text()` calls across 24 files used platform default encoding

### Files Fixed (24 files, ~65 encoding fixes)

| Tier | Category | Files | Fixes |
|------|----------|-------|-------|
| 1 | License/Security | `license/client/manager_activation.py`, `license/client/client.py`, `src/license/cache.py`, `src/license/crypto.py`, `src/machine_fingerprint.py`, `license_server/generate_rsa_keys.py`, `license/tools/generate_secure.py`, `scripts/admin/generate_license_secure.py` | 15 |
| 2 | Trading Data | `gui_app/schwab_auth.py`, `src/brokers/schwab_broker.py`, `src/brokers/webull_broker.py`, `src/trade_tracker.py`, `src/risk/position_cache.py`, `src/risk/position_monitor.py`, `src/services/contract_master.py`, `src/services/expiry_resolver.py`, `src/services/sod_balance_cache.py`, `src/services/lifecycle_manager.py` | 20 |
| 3 | Test Infrastructure | `tests/unit/test_risk_engine.py`, `tests/unit/test_route_audit.py`, `tests/unit/test_license_complete.py` | 14 |
| 4 | Utilities | `gui_app/routes.py`, `gui_app/database.py`, `gui_app/debug_report_service.py`, `src/selfbot_webull.py`, `scripts/system_diagnostics.py`, `scripts/check_consistency.py`, `upgrade/readiness.py` | 10 |

### Dynamic SL Profile Values (Updated Tests to Match Production)
| Profile | PT1 | PT2 | PT3 | PT4 |
|---------|-----|-----|-----|-----|
| Standard | BE (0%) | +5% | +10% | +17% |
| Conservative | BE (0%) | +3% | +8% | +15% |
| Aggressive | -2% | BE (0%) | +8% | +15% |

### QA Results (Final)
- **423/423** full unit suite — **ZERO failures, ZERO errors** (was 352 pass / 7 fail / 9 error)
- Cross-platform validated: all file I/O uses explicit `encoding='utf-8'`
- License validation flow: machine fingerprint, token storage, cache, RSA keys — all encoding-safe
- Confirmed working on Windows (tested), macOS and Linux (encoding-safe by design)

---

## Session: April 29, 2026 — Schwab Bug Fixes (20 of 20) + QA Round

### Phase 1: Original 14 Bug Fixes (P0–P2)
- **Fix 1 (P0)**: Streaming loop isolation — removed `loop=loop` from `selfbot_webull.py:8446`, streaming now runs in own thread. Added cross-loop subscription wrapper in `schwab_broker.py`.
- **Fix 2 (P1)**: OCO cancel result verification — cascade and SL sync paths now check `cancel_order()` return, abort on failure to prevent double-sell. Cleared stale `broker_pt_order_id` on OCO re-place failure.
- **Fix 3 (P1)**: Routed `get_order_status()` and `get_option_chain()` through `_make_request()` — now rate-limited, budget-tracked, and auto-retry on 429/401.
- **Fix 4 (P1)**: Removed redundant double cancel sweep in `place_stock_order()` (saved 3-5 API calls + 2s delay per sell). Fixed SELL_SHORT misclassified as exit order.
- **Fix 5a (P2)**: Deferred SL re-place now uses `dynamic_sl_price or early_stop_price` instead of base `stop_loss_price`.
- **Fix 5b (P2)**: Dynamic SL sync guards now check `broker_oco_order_id` in addition to `broker_stop_order_id` — fixes 4 sites where SL sync was blocked after OCO cascade.
- **Fix 5c (P2)**: Added Schwab, Tastytrade, Robinhood, Trading212 to `_extract_broker()` in broker_sync_service.
- **Fix 6 (P2)**: Streaming `stop()` now closes WebSocket + joins thread. `_connected` flag set after subscriptions restored. `_fetch_streamer_info` routed through `_make_request()`.
- Impact analysis performed before implementation — confirmed 6 of 8 fixes are Schwab-isolated, 2 affect shared logic safely.

### Phase 2: QA Audit (3 parallel agents, 27 issues found → 9 additional fixes)
- **Fix P2 #13**: `get_order_status` `is_critical` flag for exit-path callers — ensures exit orders bypass budget limits.
- **Fix P2 #14**: Reverted `asyncio.gather` to sequential in `get_option_chain` — rate limiter serializes anyway, eliminates dead `return_exceptions` code.
- **Fix P2 #15**: RESIZE_STOP only skips if OCO covers ALL shares at current SL price — prevents unprotected remainder.
- **Fix P2 #16**: OCO re-place failure in SL sync now falls back to standalone PT limit order — prevents losing PT protection.
- **Fix P3 #17**: Deferred SL price chain uses explicit `is not None` checks — prevents `0.0` falsy skip.
- **Fix P3 #18**: BUY_TO_COVER classification verified correct — is_exit, not is_entry. No change needed.
- **Fix P3 #19**: `_last_qos_time` initialized to `0.0` in `__init__` — prevents `AttributeError` if QoS check runs before first message.
- **Fix P3 #21**: Stale stop on cancel failure now enqueues deferred retry via `_enqueue_broker_op` instead of silently returning. Also handles 404/400/409 as "already dead".
- **Fix P3 #22**: Broker op queue deduplication — SYNC_STOP and RESIZE_STOP collapse to single op per position, preventing duplicate cancel+place cycles.

### Files Modified
- `src/selfbot_webull.py` — 1 line changed
- `src/brokers/schwab_broker.py` — ~60 lines changed
- `src/risk/position_monitor.py` — ~80 lines changed
- `src/services/schwab_streaming_client.py` — ~25 lines changed
- `src/services/broker_sync_service.py` — ~8 lines added

### Pending / Deferred
- `base.py` conditional order data hub fallback — still uncommitted from prior session
- `gui_app/routes.py:7781` — `get_merged_trades` NoneType crash
- All changes uncommitted — ready for commit and testing

---

## Session: April 27-28, 2026 — v9.3.2 Release + Schwab Architect Review

### Completed
- Released v9.3.2 (admin + user builds), all 7 GitHub Actions jobs passed
- Created `docs/AI_ARCHITECTURE_PROMPT.md` — architecture reference for conditional orders + risk management
- Created `docs/saas_architecture_review.html` — SaaS multi-tenant feasibility review (50 sections)
- Fixed OCO bracket cascade: prevent SL cancellation on PT tier cascade
- Fixed Schwab HTTP client recovery (`_reset_http_client` mechanism)
- Created `docs/schwab_architect_review.html` — full Schwab integration architect review
- Ran 3 parallel review agents: API compliance, schwab_broker.py audit, risk manager integration
- Validated all 20 bugs against actual source code (18 confirmed, 2 reduced scope)

### In Progress
- **20 Schwab bugs identified** — 1 P0, 4 P1, 9 P2, 6 P3 (see CLAUDE.md for full list)
- Fixes NOT yet implemented — user confirmed bugs are genuine, ready to start fixing

### Pending / Deferred
- `base.py` conditional order data hub fallback — 10 uncommitted lines, not in v9.3.2 build
- `gui_app/routes.py:7781` — `get_merged_trades` NoneType crash needs `webull_orders or []` guard
- Customer production bot (v9.3.2 user build) has Schwab errors — root cause is P0 event loop starvation

### Key Decisions
- SaaS architecture: recommended modular monolith over 20 microservices, Phase 0 validation first
- Schwab streaming fix is a 1-line change (remove `loop=loop` arg) — highest impact, lowest risk
- OCO cancel verification needs ~20 lines across 2 methods

---

## Session: April 29, 2026 — Temple of Boom Parser Implementation + QA

### Temple of Boom Signal Parser (New)
- **Created** `src/signals/temple_parser.py` — 12 parser functions covering 2 channels:
  - **Stock channel (⚡│zz)**: emoji entries (▶/⛔/🎯), NL entries ("In SYMBOL $PRICE"), exits ("Out/Cut"), trims ("Trim X%")
  - **Options channel (🚨│options-alerts💰)**: RF structured, standard (@.PRICE), traderzz1m (C/P STRIKE), Toughshit (Puts/Calls-COST C SL), options exit
- **Registered** 13 formats in `signal_format_registry.py` at priority 76-79 (safe zone between protrader_breakout@75 and learned@80+)
- **Added** `REGISTRY_TEMPLE` to `SignalSource` enum + `'temple'` mapping in `_map_registry_source()`
- **Added** exports to `src/signals/__init__.py`

### Architect Review — Gaps Found & Fixed
| # | Gap | Fix |
|---|-----|-----|
| 1 | `trim_pct` key vs expected `trim_percentage` | Changed to `trim_percentage` |
| 2 | Stock exit missing common-words guard | Added `_COMMON_EXIT_WORDS` set |
| 3 | **CRITICAL**: `temple_zz_options_b` matched standard BTO/STC | Added `(?!\s*/)` lookahead + `startswith(BTO/STC)` guard |
| 4 | `@.85` parsed as 85.0 | Fixed regex to capture leading dot |
| 5 | SL `.65` parsed as 65.0 | Same dot-capture fix |

### Remaining Architectural Gaps (Not Fixed)
- Multi-message aggregation for traderzz1m — handled by existing `signal_conversation_state.py`

### Broker Execution Validation (0DTE Expiry Fix)
- **Problem**: 5/7 Temple options parsers returned `expiry=None`, blocking `_prefetch_option_id()` (line 2087) and all broker `place_option_order()` calls
- **Fix**: Added `_default_expiry_today()` returning `datetime.now().strftime("%m/%d")` as 0DTE fallback — same approach as STACK$ 0DTE (line 6109)
- **Flag**: All parsers with defaulted expiry set `_expiry_defaulted: True` for downstream awareness
- **Affected parsers**: `temple_options_standard`, `temple_zz_options_a`, `temple_zz_options_b`, `temple_ts_options`, `temple_options_exit`
- **Result**: 7/7 options formats now execution-ready across all brokers (Webull, Schwab, Alpaca, IBKR, Tastytrade, Robinhood, Trading212)

### QA Results (Final)
- **154/154** Temple parser tests passed (99 original + 55 broker execution readiness)
- **352/368** full unit suite passed (7 failures + 9 errors all pre-existing in `test_risk_engine.py` and `test_route_audit.py`)
- Zero regressions from Temple parser addition
- All modified files pass `py_compile` syntax check
- Database init validation: OK

### Test Suite Breakdown
| Class | Tests | Focus |
|-------|-------|-------|
| `TestTempleStockPatterns` | 21 | Regex correctness for stock formats |
| `TestTempleOptionsPatterns` | 20 | Regex correctness for options formats |
| `TestTempleParserOutput` | 17 | Dict field validation |
| `TestTempleFalsePositives` | 16 | False positive rejection |
| `TestTempleEdgeCases` | 10 | Boundary conditions |
| `TestTempleRegistryIntegration` | 15 | End-to-end registry matching |
| `TestTemplePipelineSource` | 2 | Enum/mapping validation |
| `TestTempleBrokerExecution` | 55 | Broker execution field readiness |

## Session: April 30, 2026 — IBKR Live Monitor + Risk Engine Fix

### Problem
- IBKR positions not showing in Trading → Dashboard → Live Monitor tab
- Risk engine not monitoring IBKR positions

### Root Causes
1. **Field name mismatch in `ibkr_broker.py:get_positions_detailed()`**: Returned `avg_price`, `asset_type`, `call_put` — but `live_snapshot.py:_fetch_ibkr()` expected `avg_cost`, `asset`, `direction` (matching Schwab's contract). Also missing `current_price`, `unrealized_pl`, `raw_symbol` fields.
2. **Missing IBKR handler in `broker_live_analytics.py:get_open_positions()`**: Had handlers for Webull, Alpaca, Schwab, Robinhood but no IBKR — caused `/api/broker/positions/ibkr_*` to return empty.

### Files Fixed
| File | Change |
|------|--------|
| `src/brokers/ibkr_broker.py:311-367` | Rewrote `get_positions_detailed()` — field names now match Schwab contract (`avg_cost`, `current_price`, `unrealized_pl`, `asset`, `direction`, `raw_symbol`). Added `ib.tickers()` cache lookup for live prices. |
| `gui_app/broker_live_analytics.py:627` | Added `elif broker_type == 'ibkr':` handler in `get_open_positions()` — reads from `get_positions_detailed()` with correct field mapping. |

---

## April 30, 2026 — Session 2: Sync Timing, UTF-8, Alt Broker Fallback

### Fixes Applied

| # | Issue | Root Cause | Fix | File(s) |
|---|-------|-----------|-----|---------|
| 1 | **Bot crash: OSError [Errno 22] on stdout** | `_original_print` (raw `builtins.print`) wrote to invalid stdout handle (pipe/devnull) | Wrapped `_original_print` definition to catch OSError silently, protecting all 750+ call sites | `src/selfbot_webull.py:246-250` |
| 2 | **Bot crash: UnicodeEncodeError on startup** | Windows cp1252 console encoding can't render `✓`/`✅` Unicode in database.py print statements | Added `sys.stdout.reconfigure(encoding='utf-8', errors='replace')` at entrypoint + catch UnicodeEncodeError in `_original_print` | `src/selfbot_webull.py:17-28, 249` |
| 3 | **IBKR conditional order #37 no price updates** | IBKR paper account lacks NASDAQ Level 1 subscription (error 10168). P3 BrokerPriceMonitor missing `alt_broker_instances` parameter | Added `alt_broker_instances=self.broker_instances` to P3 path; added alt broker REST fallback in `_do_rest_quote()` and `_fetch_price()` backoff path | `us_service.py:119`, `base.py:958-970, 989-1003` |
| 4 | **IBKR positions not syncing** | `asyncio.to_thread(ib.positions)` caused "no current event loop in thread" — ib_insync cache reads must run on IB's event loop | Changed to direct `ib.positions()` / `ib.openTrades()` calls; added `ib.portfolio()` fallback; dual field support for `avgCost`/`averageCost` | `broker_sync_service.py:657-715` |
| 5 | **Live Monitor showing "No live trades"** | `unifiedLivePoll()` had early return when `currentTrades` was empty, preventing poller from ever discovering new positions | Removed the early return guard | `gui_app/templates/trades.html:1699-1703` |
| 6 | **Position closure blocked 5+ minutes** | Broker-level empty guard required 10 consecutive cycles AND 300 seconds before any trade reconciliation | Reduced broker guard to 2 cycles + 0s time; added per-trade 3x consecutive confirmation (45s); risk cache auto-cleanup on closure | `broker_sync_service.py:1306-1307, 1843-1882` |

### Timing Improvement (Fix #6)

**Before:** Broker closes position → 300+ seconds (5 min) broker guard + 15 min trade guard → CLOSED
**After:** Broker closes position → 2 cycles broker guard (21s) + 3 cycles per-trade confirmation (37s) → **58 seconds total** → CLOSED + risk cache cleaned

Verified live with OSRH Trade #36 on IBKR_PAPER:
```
14:35:13 — Cycle 1: broker guard 1/2 (deferred)
14:35:34 — Cycle 2: broker guard passed, per-trade 1/3
14:35:52 — Cycle 3: per-trade 2/3
14:36:11 — Cycle 4: per-trade 3/3 → OPEN → CLOSED (58s total)
```

## May 9, 2026 — Webull Official API Integration (Complete)

### Implemented
- **Phase 1**: Core module — `src/brokers/webull_official/` with 13 files
  - `auth.py`: HMAC-SHA1 per-request signing (v2 API)
  - `config.py`: Production/UAT environment config
  - `exceptions.py`: Error hierarchy (Auth, Order, RateLimit, Connection)
  - `rate_limiter.py`: Token bucket per endpoint category
  - `models.py`: WebullBalance, WebullPosition, WebullOrder, PlaceOrderResult
  - `client.py`: httpx-based async HTTP client with auto rate limiting
  - `accounts.py`, `positions.py`, `orders.py`: REST API wrappers
  - `streaming.py`: MQTT market data + trade event poller
  - `broker.py`: Main broker class implementing BotifyTrades interface
- **Phase 2**: 56 unit tests (auth, config, rate limiter, models, exceptions, orders, broker interface)
- **Phase 3**: Full integration wiring
  - `selfbot_webull.py`: Import flag, broker init block, BrokerManager, get_broker_instance, signal routing
  - `broker_credentials_service.py`: get/save/clear credentials, startup config, enabled_brokers
  - `unified_price_hub.py`: Hub registry + broker name mapping
  - `relay_client.py`: Broker name + instance mapping
  - `index.html`: GUI dropdown + JS balance URL routing
  - `routes.py`: `/api/webull_official/balance` endpoint
- **Phase 4**: 21 streaming/wiring tests (MQTT batching, event poller, credential service, broker resolution)

### Test Results
- **539 total tests, 0 failures, 0 regressions**
- New tests: 77 (28 auth + 28 trading + 21 streaming/wiring)
- Existing tests: 462 — all pass unchanged

## Session: May 28, 2026 — Duplicate Position Fix

### Bug: Sync creates duplicate trade records (HOTH, GNS)
- **Root cause 1**: `_import_manual_trades()` in `broker_sync_service.py` checked for duplicates only by symbol+broker in OPEN/PENDING trades. If the trade was briefly CLOSED or the order_id differed in case, a duplicate was created with `source='sync_discord'`.
- **Root cause 2**: `trade_monitor.py` `_add_bto_to_trades_table()` had zero dedup — blindly inserted, creating parallel entries alongside the signal-execution path.
- **Root cause 3**: `trade_monitor` also created entries in `webhook_positions` table, which the dashboard displayed alongside `trades` table entries — visual duplicate.

### Fixes Applied
- `broker_sync_service.py`: Added `order_id` dedup check across ALL trade statuses (not just OPEN/PENDING) via direct DB query before the symbol+broker fuzzy check
- `trade_monitor.py`: Added `order_id` and symbol+broker dedup checks in `_add_bto_to_trades_table()` before inserting
- Cleaned up existing duplicates: HOTH #152, #157 (hidden), GNS webhook_position #4 (closed), stale SPY webhook_position #3 (closed)
