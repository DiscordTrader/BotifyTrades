# Balance Pipeline & Risk Engine Gap Analysis
**Date:** April 15, 2026  
**Trigger:** LRHC trade rejected on Schwab with "Settled cash is $0.00" despite user having $667.27

---

## Incident Summary

A conditional order for LRHC triggered at 08:16:04 EST and was rejected by the health monitor with:
```
SCHWAB: Settled cash is $0.00 (negative or zero) - cannot trade to avoid good faith violation
```

The user's Schwab account had $667.27 in settled cash the entire time. A DNS/network outage on the user's machine (starting ~06:26 EST) prevented the bot from refreshing balance data, and the system incorrectly interpreted stale/failed data as a zero balance.

---

## Timeline

| Time (EST) | Event |
|------------|-------|
| 06:17:42 – 06:27:32 | Schwab balance refreshes normally: BP=$667.27, Settled=$667.27 (15 successful reads) |
| 06:19:58 | First `SCHWAB returned 0 positions after internal error` |
| 06:26:05 | `[SCHWAB] Error getting account info: [Errno 11001] getaddrinfo failed` — DNS failure |
| 06:27:32 | **Last successful balance read** |
| 06:32:xx | Health monitor cache expires (5-min TTL) |
| 07:00+ | Webull also hitting DNS failures — system-wide network issue |
| 08:07:59 | "watching LRHC" signal arrives |
| 08:15:39 | "LRHC over 0.85" conditional order created |
| 08:16:04 | LRHC triggers → health check sees SettledCash=$0.00 → **REJECTED** |

---

## Root Cause Chain

1. **Network outage** (DNS resolution failure on user's machine) blocks all Schwab API calls
2. **Schwab broker returns zeros on error** (`get_account_info()` catches exception, returns `{settled_cash: 0, buying_power: 0, ...}`)
3. **Sync service treats zeros as valid data** — calls `update_broker_status(True, account_info={settled_cash: 0})`
4. **Health monitor caches zeros** as real account data
5. **Pre-trade validation rejects** because `settled_cash <= 0`

---

## All Identified Gaps (Prioritized)

### P0 — Critical: Will cause false trade rejections

#### Gap 1: Every broker returns zero-dict on API error — ✅ FIXED
All 7 brokers now return `None` on API failure instead of zero-dicts. Each broker has `_last_account_info` fallback that returns last known good data on transient errors (DNS/timeout/network). Schwab, Robinhood, Alpaca, IBKR, TastyTrade store to `_last_account_info` on success. Webull uses data hub cache (300s). Trading212 uses `_account_cache`.

#### Gap 2: Settled cash not mapped for Webull/Robinhood/Alpaca in sync service — ✅ FIXED
Sync service `_fetch_account_info` now maps `settled_cash` and `unsettled_cash` for Webull, Alpaca, and Robinhood alongside Schwab. GFV protection is now active for all brokers in the `brokers_with_settled_cash` list.

#### Gap 3: Alpaca account info never fetched — ✅ FIXED
Changed sync service Alpaca branch from `hasattr(broker_instance, 'get_account')` to `hasattr(broker_instance, 'get_account_info')` and calls `get_account_info()`. Now correctly fetches account data including settled/unsettled cash.

---

### P1 — High: Creates incorrect state or inconsistent behavior

#### Gap 4: Health monitor cache deleted on disconnect, no "last known good" — ✅ FIXED
On disconnect, cache entry is now preserved with `stale=True` and `disconnected_at` timestamp instead of being deleted. `validate_buying_power` falls through to stale cache data when fresh cache expires, logging staleness age.

#### Gap 5: `_update_health_async` swallows errors silently — PARTIALLY ADDRESSED
Gap 1 fix eliminates the root cause (brokers no longer return zeros on error, they return None). Sync service `if raw:` checks now correctly skip None results without poisoning cache. Full degraded-state tracking deferred to future work.

#### Gap 6: Connected + no cache = trade ALLOWED (contradicts fail-safe) — ✅ FIXED
`validate_buying_power` now checks stale cache entries (preserved by Gap 4 fix) before falling through to the connected-but-no-cache path. Stale data with real buying power values is preferred over blind pass-through. Only falls through to `return True` when no cache entry exists at all (first connection, before any data is fetched).

#### Gap 7: Robinhood portfolio_value key mismatch — ✅ FIXED
Changed sync service Robinhood branch from `raw.get('portfolio_cash')` to `raw.get('portfolio_value')` to match what the broker actually returns. Also added `settled_cash` and `unsettled_cash` mapping.

---

### P2 — Medium: Missing resilience features

#### Gap 8: No proactive balance recovery when network restores — DEFERRED
Sync loop runs every ~30s with a 60s account fetch throttle. No event-driven "network restored → immediately refresh" mechanism. Recovery takes up to 90s after network comes back. With Gap 1+4 fixes, stale data is served during outage, reducing urgency.

#### Gap 9: Conditional orders don't force a fresh balance check at trigger time — ✅ FIXED
Added pre-execution buying power validation in `conditional_order_service.py._execute_order()`. Before calling the execution callback, it now calls `health_monitor.validate_buying_power()` with the calculated required amount. On failure, the order is marked ERROR with `INSUFFICIENT_FUNDS` event and not executed.

#### Gap 10: Trading212 has no account info branch in sync service — ✅ FIXED
Added TRADING212 branch to `_fetch_account_info` that calls `get_account_info()` and maps `portfolio_value`, `buying_power`, `cash`, `invested`, and `ppl`.

#### Gap 11: Webull error dict has inconsistent schema — ✅ FIXED
Webull error path now returns `None` instead of an inconsistent zero-dict. On error, falls back to hub cache (300s TTL) before returning None. No more schema mismatch between success and error paths.

---

### Gap 12: STC-while-PENDING — Cancel unfilled BTO when STC arrives — ✅ FIXED
When an STC signal arrives and the matching trade is PENDING (BTO not yet filled), the system now:
1. Cancels the pending BTO order on the broker via `cancel_order()`
2. Marks the trade as CANCELLED with a descriptive note
3. Returns early without attempting the STC execution

Previously, the STC would be forwarded for execution against a non-existent position, resulting in broker rejection ("No matching position").

---

## Recommended Fixes (in order)

1. ~~**Stop returning zeros on error**~~ — ✅ Done
2. ~~**Map settled_cash for all brokers**~~ — ✅ Done
3. ~~**Fix Alpaca method name**~~ — ✅ Done
4. ~~**Fix Robinhood portfolio_value key**~~ — ✅ Done
5. ~~**Add Trading212 branch**~~ — ✅ Done
6. ~~**Force fresh balance check on conditional order trigger**~~ — ✅ Done
7. ~~**Cancel unfilled BTO when STC arrives**~~ — ✅ Done
8. **Mark broker degraded on repeated fetch failures** — DEFERRED (low priority with Gap 1 fix)

---

## CBlast-alerts Risk Engine Issue

### Finding
CBlast-alert channel (Discord ID: `1308282863795437659`) has risk management properly configured in the database:
- `risk_management_enabled = 1`
- `stop_loss_pct = 15%`
- `profit_target_1_pct = 10%`
- `profit_target_2_pct = 20%`
- `exit_strategy_mode = hybrid`

### Why Risk Engine Doesn't Monitor It

**The CBlast-alert Discord channel (`1308282863795437659`) is NOT in the bot's monitored channels list.**

The bot monitors only 3 channels:
- `1293555678111072347` (phoenix)
- `1443262702515650713` (pro-trader)
- `1178749711163859025` (jacob)

The risk engine monitors **open positions (trades)** in the database — not channels directly. It only applies risk settings when:
1. A trade exists in the `trades` table with `status = OPEN`
2. The trade's `channel_id` matches a channel that has `risk_management_enabled = 1`

Since CBlast-alert's channel is not monitored by the Discord selfbot, **no signals from that channel are ever processed**, no trades are created with that channel_id, and therefore the risk engine has nothing to apply its risk settings to.

### Fix
Add CBlast-alert's Discord channel ID (`1308282863795437659`) to the bot's monitored channels list via the GUI Settings → Channels page. Once the channel is monitored:
1. Signals from CBlast-alert will be parsed and trades created
2. Trades will have `channel_id = 1308282863795437659`
3. Risk engine will find the channel's risk settings and apply SL/PT monitoring

---

## Architecture Diagram

```
Signal Flow:
Discord Channel → Selfbot (monitored channels only) → Signal Parser → Trade Created (channel_id set)

Risk Flow:
Position Monitor Loop (every ~30s)
  → Fetch all open positions from all connected brokers
  → For each position, lookup trade in DB
  → Join trade.channel_id → channels.risk_management_enabled
  → If enabled: apply channel's SL/PT/trailing settings
  → If not enabled: check global risk settings

Balance Flow:
Sync Service Loop (every ~30s)
  → For each broker: fetch positions + account info
  → _fetch_account_info → broker.get_account_info()
  → On success: update health monitor cache (buying_power, settled_cash, etc.)
  → On failure: broker returns None (not zeros), sync skips cache update
  → Broker internally serves _last_account_info fallback on transient errors
  → Health monitor cache (TTL: 300s, preserved as stale on disconnect)
  → Pre-trade validation reads cache → stale fallback → connected pass-through
  → If settled_cash <= 0: REJECT (good faith violation)

STC-while-PENDING Flow:
  → STC signal arrives → pre-check finds matching trade
  → If trade status = PENDING (BTO not filled):
    → Cancel BTO order on broker
    → Mark trade CANCELLED
    → Return early (no STC execution attempted)
```
