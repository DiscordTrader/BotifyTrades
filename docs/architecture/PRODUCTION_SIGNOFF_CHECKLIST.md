# PRODUCTION SIGN-OFF CHECKLIST — BotifyTrades v2

**Audit Date:** 2026-06-24  
**Auditor:** Senior Fintech Architect — Final Production Sign-Off  
**Brokers Reviewed:** Webull Official, IBKR, Schwab, Alpaca, Tastytrade, Robinhood, Webull Legacy, Trading212

---

## OVERALL VERDICT: CONDITIONAL PASS

**Score: 31/39 sub-items PASS (79.5%) — 2 Critical, 3 High, 5 Medium defects**

System is production-viable because broker sync retroactively corrects fill prices within ~60s,
but real-time P&L display and initial Discord notifications use intended limit prices instead of
actual fills until sync runs.

---

## PATH 1: ENTRY FILL PRICE — FAIL (Critical)

**Root Cause:** `OrderResult.price` is dropped during dict conversion in `execute_on_single_broker`.
The `resp` dict contains `success/msg/orderId/executed_qty` but NEVER `fill_price` or `price`.
Downstream DB save always falls back to `signal.get('price')` — the intended limit, not actual fill.

**Location:** `selfbot_webull.py`
- Options: lines 19262–19268
- Stocks: lines 19490–19496
- Brackets: lines 18735–18741
- DB fallback: line 22532 → `broker_resp.get('fill_price') or broker_resp.get('price') or signal.get('price')`

**Fix:** Add `'fill_price': getattr(result, 'price', None)` to all three resp dict conversion blocks.

| Broker | Verdict | Fill Source | Issue |
|--------|---------|-------------|-------|
| **IBKR** | PASS (broker) | `trade.orderStatus.avgFillPrice` (ibkr_broker.py:656,764) | Real fill from IB API. Lost in selfbot dict conversion. |
| **Schwab** | FAIL | `status_result.get('price', price)` (schwab_broker.py:1409) | Key mismatch: `get_order_status` returns `'average_price'` (line 3701), NOT `'price'`. Always falls back to limit. Fix: `.get('average_price', price)` |
| **Webull Official** | FAIL | `OrderResult.price = limit price` (broker.py:417) | `PlaceOrderResult` (models.py:131-134) has no price field. Never queries fill. Fix: poll `get_order_status` (line 728) after placement. |
| **Alpaca** | PARTIAL (Med) | `price=price if price else filled_avg_price` (alpaca_broker.py:318) | Prefers limit for limit orders. Fix: `price=float(order.filled_avg_price or price or 0)` |
| **Tastytrade** | FAIL | `OrderResult.price = limit price` (tastytrade_broker.py:710) | `get_fills()` (lines 562-577) correctly computes weighted avg fill but never called at placement. |
| **Robinhood** | PARTIAL (Med) | Stocks: `price or order.get('average_price')` (line 790). Options: `price` always (line 919) | Stocks: uses limit first. Options: always limit. |
| **Webull Legacy** | PARTIAL (Med) | `OrderResult.price = price` (webull_broker.py:1193,1654) | `avgFilledPrice` available in response.data but never extracted. |
| **Trading212** | PARTIAL (Med) | `OrderResult.price = price` (trading212_broker.py:438) | `filledQuantity` available but no fill price extraction. |

---

## PATH 2: EXIT FILL PRICE — PARTIAL (High)

Same dict-conversion root cause as Path 1. Exit fill prices initially wrong but **mitigated by
broker sync's 5-priority waterfall** (Path 4) which retroactively corrects within one sync cycle (~60s).

| Sub-path | Verdict | Evidence |
|----------|---------|----------|
| Multi-broker path | PARTIAL | `selfbot_webull.py:22532` — `broker_resp.get('fill_price')` → None → falls back to `signal.get('price')` |
| Single-broker path | PARTIAL | Same dict conversion issue |
| Risk engine STC | PARTIAL | `position_monitor.py:8653` — `stc_signal['price']` = current streaming price (best-available, not actual fill) |

**Mitigation:** Broker sync 5-priority waterfall retroactively corrects exit fills. Initial Discord notification wrong; DB corrected within ~60s.

---

## PATH 3: P&L COMPUTATION — PARTIAL (High for shorts, Medium for multiplier)

| Item | Verdict | Evidence |
|------|---------|----------|
| **Formula** | PASS | `(exit - entry) * qty * multiplier` consistent in 10+ locations: database.py:3397,3937,3992,4034; routes.py:7216; broker_sync_service.py:1684,2322; position_monitor.py:1381 |
| **Options multiplier** | PARTIAL (Med) | Correctly 100 for options, 1 for stocks everywhere EXCEPT `routes.py:2571-2572` which hard-codes `*100` without `asset_type` check |
| **Short direction** | FAIL (High) | ALL formulas use `(exit - entry)` — inverted for shorts. No direction check anywhere. Real-world impact: Low if shorts not traded; High if ever enabled. |
| **Zero-price guard** | PASS | Comprehensive: sync skips P&L when price=0 (broker_sync_service.py:1682-1701), routes gates on `current_price > 0` (7209), database checks both prices > 0 (3395), ABSURD PNL GUARD defers exits 3 cycles (position_monitor.py:4511-4536) |

---

## PATH 4: BROKER SYNC CORRECTIONS — PASS

| Item | Verdict | Evidence |
|------|---------|----------|
| **PENDING→OPEN** | PASS | `broker_sync_service.py:1519-1531` — sets `executed_price = position['avg_price']` (broker avg_cost). Recalculates SL/PT using actual fill vs trigger with 50% divergence guard (lines 1533-1557). |
| **OPEN→CLOSED waterfall** | PASS | 5-priority confirmed: (1) broker bracket OCO fill (line 2182), (2) Schwab BTO child fills (2196), (3) execution_closures table (2213), (4) filled_orders by trade_id (2241), (5) filled_orders by symbol+time (2262). Each only runs if previous failed. |
| **Data corruption guard** | PASS | pnl only written if not None (1697); current_price only if > 0 (1700). No path overwrites valid data with zero/None. |

---

## PATH 5: MARKET vs LIMIT ORDER FLOW — PASS

| Item | Verdict | Evidence |
|------|---------|----------|
| **entry_order_mode** | PASS | `selfbot_webull.py:10403-10406` reads channel config. Central dispatch sets `_use_market_order=True` → converts to `price=None`. All 8 brokers interpret `price=None` as market. |
| **sl_order_mode + TIERED URGENCY** | PASS | `position_monitor.py:8455-8483` — 3-tier: stop_loss/dynamic_sl → auto market (8466-8468); trailing/giveback → aggressive chase (8470-8474); 2x SL loss → emergency market (8481-8483). |
| **trim_order_mode** | PASS | `position_monitor.py:8496-8511` — market/limit modes handled. Flows through channel_settings for all signal construction blocks. |
| **WO MARKET strips price** | PASS | `webull_official/orders.py:45-46,146-147` — `limit_price` only added to payload if not None. |
| **Schwab SEAMLESS conversion** | PASS | `schwab_broker.py:1065-1118` — `_get_aggressive_exit_price()` computes bid-minus-tick. Line 1253: MARKET→aggressive LIMIT in SEAMLESS. STOP orders forced to NORMAL session (2774-2776). |

---

## PATH 6: CONDITIONAL ORDER PIPELINE — PASS

| Item | Verdict | Evidence |
|------|---------|----------|
| **UPH event-driven monitoring** | PASS | `base.py:151` StreamingPriceMonitor. Lines 237-241: `UPH.subscribe_symbol()` pushes to ALL broker hubs. Lines 377-395: UPH + direct IBKR hub events. Lines 252-261: Tastytrade DXLink. Lines 268-284: WO MQTT. Lines 320-335: Schwab WebSocket. BrokerPriceMonitor (843) as REST fallback. |
| **150ms confirmation window** | PASS | `base.py:2571-2584` — `_confirmation_window_s` default 0.15 (line 2582). Requires price to hold across 2+ tick arrivals. Filters single-tick spikes. |
| **Trigger→execution dispatch** | PARTIAL (Low) | `base.py:2929` — single `execution_callback` to bot's multi-broker loop. Not `asyncio.gather` per-broker but functionally correct; conditional orders are typically single-broker. |
| **Notification after execution** | PASS | `base.py:2990-2993` — "Send trigger notification ONLY after execution succeeds." Gated by `if callback_success`. Failed executions get separate error notifications (3024-3027). |

---

## PATH 7: RISK ENGINE — PASS

| Item | Verdict | Evidence |
|------|---------|----------|
| **Streaming price overlay** | PASS | `position_monitor.py:1992-2053` — UPH first, per-hub fallback (Webull/Schwab/IBKR/Tastytrade). Non-streaming brokers get cross-broker subscriptions (2078-2079). |
| **Adaptive staleness** | PASS | Base 5s (line 1735). Adaptive: tick gap ≥10s → up to 30s (4859-4860); extended hours → 300s (4861-4862). REST override allows SL eval when REST confirms fresh (4865-4873). Cross-hub freshness (9309-9410). |
| **Anti-short 3-layer** | PARTIAL (Med) | Layer 1: qty math (risk_engine.py:689,348,475). Layer 2: position-exists for IBKR/Schwab/WO (position_monitor.py:7957-8003). Layer 3: WO broker rejection detection (broker.py:430-438). **GAP:** Layer 2 missing for Alpaca/Robinhood/Tastytrade/Webull Legacy/Trading212. |
| **OCO bracket placement** | PASS | Full lifecycle: cache (risk_types.py:362-365), fill detection by price proximity (5664-5669), stale reset (4638), OCO suppression (5011), bracket sync on escalation/trailing. |
| **Market escalation persists** | PASS | `position_monitor.py:8523-8524` — `stc_signal['_use_market_order'] = True` flows to `order_price = None` (8654-8655) and `force_market=True` (8694-8695). |
| **WO MARKET CORE retry** | PASS | `broker.py:439-443` — retries as MARKET/CORE/DAY on rejection. Anti-short detection (430-438) prevents retry on would-create-short. After-hours: MARKET→LIMIT+GTC (367-370). |

---

## PATH 8: DASHBOARD PRICES — PASS

| Item | Verdict | Evidence |
|------|---------|----------|
| **6-layer zero-price defense** | PASS | L1: Per-broker last-good caches (Schwab:606-609, IBKR:709-713, WO:1041-1045). L2: Streaming overlay guard (1359-1361). L3: `_build_prices` global cache (1493-1525). L4: Frontend JS `> 0` guards (trades.html:1046-1061). L5: Frontend cache (1063-1068). L6: P&L skip (routes.py:7209). |
| **Per-broker last-good cache** | PASS | Thread-safe: `_schwab_last_good_prices` (535+lock), `_ibkr_last_good_prices` (645+lock), `_wo_last_good_prices` (979+lock), `_last_good_prices_global` (1490+lock). Stale eviction (1502-1506). |
| **_LIVE suffix normalization** | PASS | `live_snapshot.py:1115-1121` — `_make_match_key()` strips `_LIVE`/`_PAPER` suffixes. Prevents duplicate positions. |
| **Frontend JS priceData guard** | PASS | `trades.html:1046-1061` — bid/ask/mid/last individually gated on `!= null && > 0`. Cache (1063-1068) preserves last good value. |

---

## PATH 9: ORDER CHASE — PASS

| Item | Verdict | Evidence |
|------|---------|----------|
| **WO in broker_map** | PASS | `unfilled_order_chaser.py:2148-2181` — all case variants mapped: `webull_official`, `WEBULL_OFFICIAL`, `Webull_Official`, `_LIVE`, `_PAPER`. All 8 brokers present. |
| **Exit: MID→BID→MARKET** | PASS | `_calc_chase_price()` (1370-1387): attempt ≤1 → MID (1374), attempt 2 → BID (1382), attempt ≥3 → MARKET/price=0 (1387). Market STC confirmed at line 1513. |
| **Entry: ASK chase** | PASS | `_get_entry_chase_price()` (1862-1946): streaming hub ask (1881,1883), REST fallback ask (1892,1894), stocks hub ask (1904), REST ask (1920,1935). Gated by `_entry_chase_enabled`. |

---

## PATH 10: AI CO-PILOT — PASS

| Item | Verdict | Evidence |
|------|---------|----------|
| **MCP 22 tools** | PASS | `src/ai/mcp_server.py:17-160` — exactly 22 tools in `_TOOL_SCHEMAS`. HTTP routes at `routes.py:10278-10302`. |
| **Chatbot + MCP + Diagnostic** | PASS | `chat_assistant.py:1712-1724` — chains MCP Co-Pilot (14 NL patterns, 1435-1461) then Diagnostic Engine (3-tier: template / rule-based 15+ patterns / AI). |
| **Auto-learn pipeline** | PASS | `format_learning_pipeline.py` — 5-stage: extract → buffer → analyze (heuristic+AI) → display → approve/reject via chatbot (chat_assistant.py:3131-3251). |
| **Feature flags** | PASS | `src/ai/feature_flags.py` — DB table `ai_feature_flags`, `is_enabled()` with 30s cache, `set_enabled()`, `get_all_flags()`. MCP tool `get_ai_feature_status` exposes via API. |

---

## DEFECT SUMMARY

### Critical (Fix Before Next Release)

| ID | Title | Location | Fix | Effort |
|----|-------|----------|-----|--------|
| **CRIT-1** | Fill price dropped in OrderResult→dict conversion | `selfbot_webull.py:19262,19490,18735` | Add `'fill_price': getattr(result, 'price', None)` to all 3 dict blocks | 5 min |
| **CRIT-2** | Schwab fill price key mismatch | `schwab_broker.py:1409,1751` | Change `.get('price', price)` → `.get('average_price', price)` | 2 min |

### High (Fix in Next Sprint)

| ID | Title | Location | Fix |
|----|-------|----------|-----|
| **HIGH-1** | Short position P&L inverted | All P&L formulas | Add `direction_mult = -1 if direction == 'short' else 1` |
| **HIGH-2** | WO never queries fill price | `webull_official/broker.py:417` | Poll `get_order_status` after placement |
| **HIGH-3** | Tastytrade never queries fill price | `tastytrade_broker.py:710` | Call `get_fills()` for order_id after placement |

### Medium (Batch into Fill-Accuracy Sprint)

| ID | Title | Location | Fix |
|----|-------|----------|-----|
| **MED-1** | Alpaca prefers limit over `filled_avg_price` | `alpaca_broker.py:318` | Prefer `filled_avg_price` over limit |
| **MED-2** | Hard-coded `*100` multiplier | `routes.py:2571-2572` | Add `asset_type` check |
| **MED-3** | Anti-short Layer 2 missing for 5 brokers | `position_monitor.py:7957-7989` | Add position verification |
| **MED-4** | Robinhood options always return limit price | `robinhood_broker.py:919` | Query order details for `average_price` |
| **MED-5** | Webull Legacy + Trading212 return limit | `webull_broker.py:1193`, `trading212_broker.py:438` | Extract fill from API response |

---

## PRODUCTION RECOMMENDATION

**SHIP WITH MONITORING.** The system is production-viable because:

1. Broker sync retroactively corrects fill prices within ~60s (PENDING→OPEN corrects entry; 5-priority waterfall corrects exit)
2. P&L is eventually consistent — initial values may be off but are corrected by next sync cycle
3. Risk engine operates on streaming prices, not fill prices — risk decisions are unaffected
4. 6-layer zero-price defense prevents $0 corruption in dashboard
5. All order flow modes (market/limit/tiered urgency) work correctly end-to-end
6. Conditional order pipeline has proper confirmation, staleness guards, and post-execution notification

**Immediate hotfix (< 10 min):** CRIT-1 (dict conversion) + CRIT-2 (Schwab key mismatch)  
**Next sprint:** HIGH-2 + HIGH-3 (broker fill queries) + MED-1/4/5 (fill accuracy)  
**Deferred:** HIGH-1 (short P&L) — only if shorts will be traded  

---

## DEEP VERIFICATION ADDENDUM

### Market Order Escalation — Cache Persistence (Path 7.5 Detail)

**Verified PASS.** The `use_market_order` flag is a persistent field on the position cache entry
(`risk_types.py:375 — use_market_order: bool = False`). It is set to `True` at:
- Emergency exit: `risk_types.py:587`
- Retry threshold reached: `risk_types.py:603-604` (`exit_retry_count >= MARKET_ORDER_THRESHOLD`)

It persists across all retry cycles and is only reset on successful exit (`risk_types.py:639`).
The position cache method `should_use_market_order()` (`position_cache.py:860-863`) reads this flag.
This means once a limit order fails enough times, the position permanently uses market orders
until the exit succeeds — exactly correct behavior.

### PENDING→OPEN Potential Null Write (Path 4 Detail)

**Minor edge case identified.** `broker_sync_service.py:1528` writes
`current_price=position.get('current_price')` which could be `None` if the broker position
lacks this field. The `update_trade()` function (`database.py:4324-4343`) is generic and will
write `current_price=NULL` to DB. However, this is self-healing: the very next OPEN sync cycle
(line 1700) only writes `current_price` when `> 0`, so the NULL is overwritten within 60s.
**Severity: Negligible.** No action required.

### Conditional Order Multi-Broker Dispatch (Path 6.3 Detail)

**Mechanism verified.** `selfbot_webull.py:11022-11024` — when conditional order has
`all_brokers` list with >1 entry, sets `signal['_enabled_brokers'] = all_brokers` which
triggers the bot's existing multi-broker dispatch loop. Single-broker orders use
`signal['_broker_override']` (line 11026). The callback at `base.py:2929` delegates to
`execute_conditional_order()` which builds a synthetic BTO signal and feeds it through
the same pipeline as manual signals. Not `asyncio.gather` per-broker, but leverages the
proven multi-broker execution infrastructure.

### Broker-Level Fill Price Evidence Summary

| Broker | API Field Available | Extracted at Placement? | Where Used Instead |
|--------|-------------------|------------------------|-------------------|
| IBKR | `orderStatus.avgFillPrice` | Yes (ibkr_broker.py:656) | Lost in dict conversion |
| Schwab | `order.price` → `average_price` key | No (wrong key used) | `get_order_status` returns `'average_price'` |
| Webull Official | `order.filled_price` (get_order_status:728) | No (never queried) | `PlaceOrderResult` has no price field |
| Alpaca | `order.filled_avg_price` | Partially (only for market) | Limit price preferred for limit orders |
| Tastytrade | `leg.fills[].fill_price` | No (only in `get_fills()`) | `get_fills()` never called at placement |
| Robinhood | `order.average_price` | Partially (stocks only) | Options always use limit price |
| Webull Legacy | `response.data.avgFilledPrice` | No | Limit price used in OrderResult |
| Trading212 | `order_data.filledQuantity` (no price) | No | Limit price used in OrderResult |

---

*Checklist generated from code-level audit of all 8 brokers across 10 critical paths with line-number evidence.*
*Deep verification pass completed 2026-06-24 with targeted reads on cache persistence, null writes, and multi-broker dispatch.*
