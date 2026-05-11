# BotifyTrades Progress Log

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
