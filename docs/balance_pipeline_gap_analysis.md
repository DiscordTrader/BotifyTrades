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

#### Gap 1: Every broker returns zero-dict on API error
All brokers return `{buying_power: 0, settled_cash: 0, ...}` when the API fails, making errors indistinguishable from genuinely empty accounts.

| Broker | Error Return | File:Line |
|--------|-------------|-----------|
| Schwab | `{buying_power: 0, settled_cash: 0, ...}` | schwab_broker.py:808 |
| Webull | `{buying_power: 0, cash: 0, portfolio_value: 0}` | webull_broker.py:640 |
| Robinhood | `{buying_power: 0, settled_cash: 0, ...}` | robinhood_broker.py:172, 230 |
| Alpaca | `{buying_power: 0, settled_cash: 0, ...}` | alpaca_broker.py:197 |
| IBKR | `{buying_power: 0, ...}` | ibkr_broker.py:147, 192 |
| TastyTrade | `{buying_power: 0, ...}` | tastytrade_broker.py:245, 282 |
| Trading212 | `{buying_power: 0, ...}` | trading212_broker.py:176 |

Only Schwab has `_last_account_info` fallback, but it only activates during 429 rate-limit backoff — NOT during network/DNS failures.

#### Gap 2: Settled cash not mapped for Webull/Robinhood/Alpaca in sync service
The sync service (`broker_sync_service.py`) only maps `settled_cash` to the health monitor for Schwab (lines 1041-1042). For Webull, Robinhood, and Alpaca — even though the brokers calculate and return it — the sync service drops it.

But the health monitor validates `settled_cash` for ALL of them (line 549: `brokers_with_settled_cash = ['WEBULL', 'ALPACA', 'ALPACA_PAPER', 'ROBINHOOD', 'SCHWAB']`).

**Result:** GFV (Good Faith Violation) protection is silently bypassed for Webull, Robinhood, and Alpaca — the `settled_cash` key is never in cache, so it falls through to the standard buying_power check.

#### Gap 3: Alpaca account info never fetched
Sync service checks `hasattr(broker_instance, 'get_account')` for Alpaca (line 1021), but AlpacaBroker exposes `get_account_info()`, not `get_account`. Health data for Alpaca is always empty.

---

### P1 — High: Creates incorrect state or inconsistent behavior

#### Gap 4: Health monitor cache deleted on disconnect, no "last known good"
When `update_broker_status(is_connected=False)` is called, the cache is immediately wiped (line 284). Once the 5-minute TTL passes, there's nothing. When a fresh fetch returns zeros (Gap 1), those zeros overwrite the blank cache and become "truth."

#### Gap 5: `_update_health_async` swallows errors silently
When account fetch times out (line 479-480) or throws an exception (line 483-484), the health monitor is never updated. The broker remains marked as "connected" even though it's been failing for hours. No degraded state exists.

#### Gap 6: Connected + no cache = trade ALLOWED (contradicts fail-safe)
When cache is `None` but broker is marked connected (line 538-540), `validate_buying_power` returns `True` — allowing the trade with zero validation. The code comment says "FAIL-SAFE: Missing cache returns False" but the actual behavior is the opposite for connected brokers.

#### Gap 7: Robinhood portfolio_value key mismatch
Sync service maps `raw.get('portfolio_cash')` (line 1055) but Robinhood broker returns `portfolio_value` (line 223). Portfolio value is always $0, suppressing daily P&L limit updates.

---

### P2 — Medium: Missing resilience features

#### Gap 8: No proactive balance recovery when network restores
Sync loop runs every ~30s with a 60s account fetch throttle. No event-driven "network restored → immediately refresh" mechanism. Recovery takes up to 90s after network comes back.

#### Gap 9: Conditional orders don't force a fresh balance check at trigger time
When LRHC triggered, it used stale/zero cached data. No mechanism to do a real-time balance fetch before executing a conditional order.

#### Gap 10: Trading212 has no account info branch in sync service
Trading212 is in the sync broker list but `_fetch_account_info` has no case for it. Health always gets empty account info.

#### Gap 11: Webull error dict has inconsistent schema
Success path returns `settled_cash`, `unsettled_cash` (lines 626-627). Error path (line 640) returns only `buying_power`, `cash`, `portfolio_value` — missing the settled cash keys. Creates inconsistent data shapes between success and error.

---

## Recommended Fixes (in order)

1. **Stop returning zeros on error** — All brokers should return `None` on fetch failure. On transient errors (DNS/timeout/network), serve `_last_account_info` as fallback with a staleness indicator.

2. **Add data quality to health monitor** — Track `fresh` / `stale` / `fetch_failed` state. Never overwrite good data with failed-fetch zeros.

3. **Map settled_cash for all brokers** — Add `settled_cash` and `unsettled_cash` to Webull, Robinhood, and Alpaca branches in `_fetch_account_info`.

4. **Fix Alpaca method name** — Change `get_account` to `get_account_info` in sync service.

5. **Fix Robinhood portfolio_value key** — Map `portfolio_value` not `portfolio_cash`.

6. **Add Trading212 branch** — Add account info fetching for Trading212 in sync service.

7. **Force fresh balance check on conditional order trigger** — Before executing, fetch live account data with a short timeout.

8. **Mark broker degraded on repeated fetch failures** — Don't leave it as "connected" when account info keeps failing.

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
  → On failure: ⚠️ CURRENT: returns zeros, cache poisoned
                 ✅ SHOULD: return None, preserve last known good data
  → Health monitor cache (TTL: 300s)
  → Pre-trade validation reads cache
  → If settled_cash <= 0: REJECT (good faith violation)
```
