# BotifyTrades Progress Log

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
