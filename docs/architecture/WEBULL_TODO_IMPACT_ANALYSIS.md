# Webull Official — TODO Implementation Impact Analysis

**Date**: 2026-06-20
**Scope**: 3 remaining TODO features — OCO/OTOCO, gRPC Events, Order Preview
**Method**: Full dependency trace across all callers, data models, UI, and tests

---

## Executive Summary

| Feature | Breaking Changes | UI Changes | Risk Level | Effort | Recommendation |
|---|---|---|---|---|---|
| **OCO/OTOCO** | 6 code paths must change | 0 (none needed) | 🟡 MEDIUM | ~200 lines | ✅ Implement — biggest reliability win |
| **gRPC Events** | 0 breaking | 1 CSS class | 🟢 LOW | ~300 lines | ✅ Implement — latency win, 0 risk |
| **Order Preview** | 0 breaking | 0 (optional) | 🟢 NONE | ~100 lines | ✅ Implement — simple, additive |

**Bottom line: None of these break existing functionality.** OCO requires careful changes in position_monitor.py but the infrastructure already exists (Schwab uses it). gRPC and Preview are purely additive.

---

## Feature 1: OCO/OTOCO Combo Orders

### Will it break anything? **No, if implemented correctly.**

The existing independent-order path continues to work. OCO is an enhancement that links SL+PT at the broker level. If OCO placement fails, the code can fall back to independent orders.

### Existing Infrastructure (already built)

| Component | Status | Location |
|---|---|---|
| `broker_oco_order_id` field | ✅ Exists | `risk_types.py:362` |
| `broker_oco_sl_price` field | ✅ Exists | `risk_types.py:363` |
| `broker_oco_pt_price` field | ✅ Exists | `risk_types.py:364` |
| `broker_oco_qty` field | ✅ Exists | `risk_types.py:365` |
| OCO fill detection logic | ✅ Exists | `position_monitor.py:5570-5618` |
| OCO PT fill → cancel SL | ✅ Exists | `position_monitor.py:5634` |
| OCO cancel in bracket cleanup | ✅ Exists | `position_monitor.py:6862-6868` |
| PT sell suppression when OCO active | ✅ Exists | `position_monitor.py:4960-4962` |
| Schwab OCO reference pattern | ✅ Exists | `position_monitor.py:5848` |
| `place_bracket_order()` (OTOCO) | ✅ Exists | `orders.py:111-188` |
| `PlaceOrderResult.combo_order_id` | ✅ Exists | `models.py:133` |

### What Needs to Change (6 areas)

```
 #  Area                     File:Lines                   Change Type     Breaking?
 ─────────────────────────────────────────────────────────────────────────────────
 1  Initial bracket          position_monitor.py:6252-6314  Modify          No
    → Use OCO when both SL+PT needed (stocks only)
    → Set cache.broker_oco_* fields
    → Fall back to independent orders for options (DAY TIF)

 2  SL escalation            position_monitor.py:7254-7330  Modify          No
    → Cancel OCO combo → re-place with new SL + same PT
    → Follow Schwab pattern at lines 6930-6975

 3  PT cascade               position_monitor.py:6456-6740  Add WO branch   No
    → Cancel OCO → re-place with PT(N+1) + current SL
    → Follow Schwab pattern at lines 6537-6580

 4  PT replace               position_monitor.py:7635-7696  Modify          No
    → Cancel OCO → re-place with new PT + same SL
    → Follow Schwab pattern at lines 7487-7540

 5  Native trailing upgrade  position_monitor.py:7366-7402  Modify          No
    → Cancel OCO first (not just SL leg)
    → Then place trailing stop + standalone PT

 6  New OrdersAPI method     orders.py                      Add             No
    → place_oco_order() for exit-only OCO (no entry trigger)
    → combo_type fields: client_combo_order_id, two legs
```

### Options Limitation

Webull restricts option sell-side to **DAY TIF only**. OCO orders typically require GTC for both legs. **Options must continue using independent orders** with daily SL re-placement via `_replay_day_tif_option_sl()`. This is not a gap — it's an API restriction.

### UI Changes: NONE

- Dashboard bracket display already reads `broker_stop_order_id` and `broker_pt_order_id` — these continue to be set alongside `broker_oco_order_id`
- Cancel bracket paths already handle OCO generically (`position_monitor.py:6862`)
- Settings page (`settings.html:5244`) already mentions OCO support
- No new UI elements, toggles, or displays needed

### Backward Compatibility

| If OCO placement fails | What happens |
|---|---|
| API returns error | Code falls back to 2 independent orders (current behavior) |
| Combo cancel fails | Individual leg cancels still attempted (existing fallback at L6867-6868) |
| Fill detection misidentifies leg | `fill_price` vs `broker_oco_pt_price/sl_price` comparison resolves (existing L5616-5618) |

---

## Feature 2: gRPC Trade/Position Events

### Will it break anything? **No. Zero breaking changes.**

gRPC is purely additive — it runs alongside the existing TradeEventPoller. If gRPC fails, the poller continues at 5s intervals.

### Critical Finding: Events Are Currently Dead Code

The TradeEventPoller **emits** fill/terminal events but `broker.py:969-972` **never registers callbacks**. The events fire into void. All fill detection happens via independent polling by BrokerSyncService (30-60s) and PositionMonitor (5-30s).

### What Needs to Change

```
 #  File                               Change Type    Lines    Breaking?
 ──────────────────────────────────────────────────────────────────────────
 1  streaming.py                        Add class      ~150     No
    → TradeEventStream (gRPC server-streaming client)
    → Emits same 'fill'/'terminal' dict format as TradeEventPoller
    → Handles: Ping, AuthError, NumOfConnExceed, SubscribeExpired

 2  models.py                           Add dataclass  ~20      No
    → WebullTradeEvent (normalized gRPC payload)

 3  broker.py                           Modify         ~30      No
    → Wire callbacks in start_streaming()
    → Use gRPC primary, TradeEventPoller fallback
    → Push fill events to position cache invalidation

 4  config.py                           Already done   0        No
    → events_url already returns 'events-api.webull.com'

 5  rate_limiter.py                     No change      0        No
    → gRPC is persistent stream, not per-request

 6  requirements.txt                    Add dep        1 line   No
    → grpclib>=0.4.7 (pure-Python, no C extension)
```

### Blocker: `grpcio` vs `grpclib`

| Library | Python 3.14 | C Extension | Status |
|---|---|---|---|
| `grpcio` | ❌ Won't compile | Yes | Documented blocker in `docs/progress.md:1039` |
| `grpclib` | ✅ Works | No (pure Python) | Recommended alternative |

### UI Changes: 1 minor CSS addition

```css
/* brokers.html — add 'filled' status class (lines 583-604) */
.order-status-filled { background-color: #22c55e; color: white; }
```

No other UI changes. Fill events flow through existing data channels.

### Performance Impact

| Metric | Before (Poller) | After (gRPC) |
|---|---|---|
| Fill detection latency | 5-50s | <100ms |
| API calls for fill detection | 12-120/min | 0 (push-based) |
| Rate limit consumption | `account_data` 2/2s budget | None (persistent stream) |
| Memory (_known_fills growth) | Unbounded (WO-20 bug) | Eliminated (event-driven) |

---

## Feature 3: Order Preview

### Will it break anything? **No. Purely additive.**

Preview is an optional pre-flight check before order placement. It uses the same request body as placement. It's gated by a config flag (off by default).

### What Needs to Change

```
 #  File                               Change Type    Lines    Breaking?
 ──────────────────────────────────────────────────────────────────────────
 1  orders.py                           Add method     ~40      No
    → preview_order() — POST identical body to /preview endpoint

 2  models.py                           Add dataclass  ~8       No
    → PreviewResult(estimated_cost, estimated_transaction_fee)

 3  broker.py                           Add gate       ~50      No
    → Before place_stock_order: if BUY + preview_enabled → preview first
    → Before place_option_order: if BUY + preview_enabled → preview first
    → On 417 → return OrderResult(success=False, message=rejection)
    → On network error → log warning, continue (fail-open)

 4  config.py                           Add flag       ~1       No
    → enable_order_preview: bool = False

 5  rate_limiter.py                     Add category   ~2       No
    → 'preview': (150, 10) — official API limit
```

### Design Decisions

| Decision | Choice | Why |
|---|---|---|
| When to preview? | **BUY-side only** | STC/SL exits must not have added latency |
| On preview failure? | **Fail-open** | Network timeout → log warning, place anyway |
| On preview 417? | **Block order** | Server says it'll reject → don't waste the placement call |
| Default state? | **Off** | Enable per-deployment via config |
| UI integration? | **None for MVP** | Server-side logging only; dashboard optional enhancement |

### Execution Latency Impact

| Scenario | Current | With Preview |
|---|---|---|
| BUY stock entry | ~200ms | ~400ms (+1 API call) |
| BUY option entry (BTO) | ~300ms | ~600ms (+1 API call) |
| STC/SL exit | ~200ms | ~200ms (preview skipped) |
| Risk engine bracket SL/PT | ~200ms | ~200ms (SELL-side, preview skipped) |

### UI Changes: NONE required

- No new buttons, modals, or displays needed for MVP
- Optional enhancement: tooltip showing estimated cost/fees on manual order buttons
- Quick close buttons (Bid/Mid/Mkt) are STC exits — never previewed

---

## Implementation Order

```
Phase 1: Order Preview (safest, smallest)                    ~100 lines
  → 0 breaking changes, 0 UI changes
  → Off by default, BUY-side only
  → Can be shipped and tested independently
  → Catches: insufficient funds, PDT restrictions, session mismatches

Phase 2: gRPC Trade Events (biggest latency win)             ~300 lines
  → 0 breaking changes, 1 CSS class
  → Runs alongside existing poller (graceful fallback)
  → Fixes: WO-20 memory leak, 5s fill detection gap
  → Also fixes: TradeEventPoller callbacks never wired (dead code)

Phase 3: OCO Combo Orders (biggest reliability win)           ~200 lines
  → 0 breaking changes if fallback retained
  → Stocks only (options keep independent orders due to DAY TIF)
  → Must follow Schwab pattern in position_monitor.py
  → 6 code paths in risk engine need careful modification
  → Eliminates: 5s gap between SL fill and PT cancellation
```

---

## Risk Matrix

| What Could Go Wrong | Probability | Impact | Mitigation |
|---|---|---|---|
| OCO: Replace on OCO leg fails | MEDIUM | SL escalation broken for that position | Cancel-and-replace entire combo (Schwab pattern) |
| OCO: Options attempt OCO with DAY TIF | LOW | API rejects | Guard: `if is_option: use independent orders` |
| OCO: Fill detection wrong leg | LOW | PT fill treated as SL or vice versa | Price comparison logic already handles this (L5616) |
| gRPC: Connection drops silently | MEDIUM | Falls back to 5s polling | Keep TradeEventPoller as automatic fallback |
| gRPC: `grpclib` incompatibility | LOW | Feature disabled | TradeEventPoller continues working |
| Preview: Adds latency to entries | LOW | 200ms slower entries | BUY-side only, config-gated, fail-open |
| Preview: Rate limit exceeded | LOW | 417 error | Dedicated `preview` rate limit category |

---

## Summary: Safe to Implement

```
                  Breaking    UI Changes    Can Ship    Risk
                  Changes     Required      Alone?      Level
 ─────────────────────────────────────────────────────────────
 Order Preview     0           0            ✅ Yes      🟢 NONE
 gRPC Events       0           1 CSS        ✅ Yes      🟢 LOW
 OCO/OTOCO         0*          0            ✅ Yes      🟡 MEDIUM

 * OCO has 0 breaking changes IF fallback to independent orders
   is retained when OCO placement fails.
```

**All three features are safe to implement. None require UI changes beyond 1 optional CSS class. All can be shipped independently. The existing system continues to work unchanged if any feature is disabled or fails.**
