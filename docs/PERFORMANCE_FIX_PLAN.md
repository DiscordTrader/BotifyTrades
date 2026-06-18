# Risk Engine Performance Fix Plan

**Date:** 2026-06-08
**Problem:** 100% of risk cycles (49/49) flagged SLOW — avg 4,400ms per cycle. GUI pages spin/unresponsive.
**Target:** <500ms per cycle under normal operation.

---

## Current Bottleneck Breakdown

| Component | Time | Notes |
|-----------|------|-------|
| Webull REST fetch | ~2,200ms | **0 positions** — pure waste |
| Schwab REST fetch | 1,100–3,300ms | 4 stock positions |
| Eval phase | ~16ms | Fast, not the problem |
| Total cycle | ~4,400ms | 99.6% spent on HTTP I/O |

Additional issues:
- Schwab streaming heartbeat timeout (180s → 3 min of stale prices)
- 8 stuck-price REST fallbacks per session
- 12 stale streaming quote events
- Sync service duplicates position fetches (separate HTTP calls)
- Flask GUI shares GIL with bot — blocked during fetch I/O

---

## Root Causes

### RC1: Empty-List Nullification (SMOKING GUN)
**File:** `src/risk/position_monitor.py:2930-2933`
```python
if hub_positions is not None and len(hub_positions) == 0:
    _empty_age = hub.get_positions_age()
    if _empty_age > 2.0:
        hub_positions = None  # ← Forces REST fetch every cycle!
```
When Webull has 0 positions, hub returns `[]`. This code converts it to `None` after 2s, forcing a full 2,200ms HTTP call that also returns 0 positions. **An empty list IS valid data.**

### RC2: `_has_open` Is Global, Not Per-Broker
**File:** `src/risk/position_monitor.py:2898`
```python
_has_open = getattr(self, '_has_open_positions_or_watches_cache', True)
```
Flag is True because Schwab has 4 positions. The discovery skip (`if not _has_open`) never fires for Webull because the flag is shared across all brokers. Webull with 0 positions gets fetched every cycle because Schwab has trades.

### RC3: REST Cache TTL = 10s, Too Aggressive
**File:** `src/risk/position_monitor.py:3086`
```python
_REST_CACHE_TTL = 10
```
Risk cycle takes ~5s, so cache expires every 2 cycles. Meanwhile hub TTLs are:
- Webull hub: 45s
- Schwab hub: 15s
- Schwab broker internal: 60s

Risk engine fetches 3-4x more aggressively than hubs recommend.

### RC4: Sync Service Duplicates Position Fetches
`broker_sync_service.py` fetches positions from Webull and Schwab every 15-30s via `get_positions_detailed()` and pushes to hubs. But the risk engine ignores this data due to 10s REST cache and 20s hub max_age — refetches independently.

### RC5: Schwab Hub TTL Misalignment
Schwab hub TTL is 15s, risk engine hub max_age is 20s, REST cache is 10s. When hub cache expires at 15s, the risk engine falls through to a full REST call (1,100-3,300ms). The sync service already feeds the hub every 15s but the risk engine doesn't trust it.

### RC6: Schwab Streaming Heartbeat Timeout Too Long
180s timeout means 3 minutes of stale prices before reconnect. During this time, stuck-price detection kicks in with expensive REST fallbacks.

---

## Fix Plan (Priority Order)

### P0: Fix Empty-List Nullification
**Impact:** Saves ~2,200ms/cycle
**Effort:** 5 minutes
**Risk:** NONE — force-refresh events bypass cache, new positions discovered via fill events

**Change:** `src/risk/position_monitor.py:2930-2933`
- Remove the empty-list-to-None conversion
- An empty list with fresh timestamp = "no positions exist" (valid data)
- Keep `None` (hub has no data at all) as the only cache miss signal

### P1: Increase REST Cache TTL and Hub Max Age
**Impact:** Saves ~1,500ms avg/cycle
**Effort:** 10 minutes
**Risk:** Low — position list updates delayed up to 30s, but prices still from streaming. Fill events trigger immediate force-refresh.

**Changes:**
- `_REST_CACHE_TTL`: 10 → 30
- `_hub_max_age`: 20 → 45 (match Webull hub TTL)
- Keep `_REST_CACHE_TTL = 0` override on force-refresh events (already exists)

### P2: Per-Broker Discovery Skip
**Impact:** Saves ~2,200ms for empty brokers
**Effort:** 15 minutes
**Risk:** Low — fill events trigger force-refresh, manual trades discovered within 60s

**Change:** `src/risk/position_monitor.py`
- Track `_has_open_*` per broker (e.g., `_has_open_webull`, `_has_open_schwab`)
- When broker has 0 positions AND no fill watches for that broker, skip REST and only discover every 60s
- Existing `_webull_discovery_ts` mechanism already supports this — just needs per-broker `_has_open` check

### P3: Trust Sync Service Data
**Impact:** Saves ~1,000ms/cycle
**Effort:** 30 minutes
**Risk:** Medium-low — sync runs every 15s, worst case 15-30s delay

**Changes:**
- Increase Schwab hub position TTL from 15s to 30s
- Risk engine: when hub returns fresh data, skip direct REST entirely
- Only fall back to direct REST when hub data >60s old AND streaming is dead
- Sync service already pushes to hubs — this just trusts it

### P4: Reduce Schwab Streaming Heartbeat Timeout
**Impact:** Faster reconnect, fewer stuck-price fallbacks
**Effort:** 1 hour
**Risk:** Low

**Changes:** `src/services/schwab_streaming_client.py`
- Reduce heartbeat timeout from 180s to 60s
- Add proactive ping every 30s (in addition to existing QOS pings)
- Faster reconnect = less time relying on REST price fallbacks

### P5: Offload Post-Fetch Parsing to Thread
**Impact:** Reduces Flask GIL contention
**Effort:** 1 hour
**Risk:** Low

**Change:** Wrap heavy position parsing in `asyncio.to_thread()` so it doesn't block the event loop during risk cycles.

---

## Expected Results

| State | Cycle Time | Notes |
|-------|-----------|-------|
| Current | ~4,400ms | 100% SLOW |
| After P0 | ~2,200ms | Webull drops to ~0ms |
| After P0+P1 | 200–500ms | Both brokers use cache |
| After P0+P1+P2 | 100–200ms | Empty brokers skipped |
| After all fixes | <200ms normal | REST only on fills/discovery |

---

## Safety Guarantees (No Position Sync Loss)

These fixes do NOT remove any capability:
- **New position discovery**: Fill events trigger `request_risk_eval()` → force-refresh (TTL=0) → immediate REST
- **Position sync**: Sync service continues fetching every 15s and pushing to hubs
- **Price updates**: Streaming provides real-time prices (not affected by REST cache changes)
- **Risk evaluation**: Eval phase is already fast (16ms) — not touched
- **Manual trade detection**: Auto-import still runs, just reads from hubs instead of direct REST
- **Fallback path**: If hub data >60s old AND streaming dead → direct REST kicks in

---

## Related Issues Found

### Startup Validation Failures (5 issues)
- `GUI Executions` channel: Risk enabled but no stop loss configured
- `GUI Executions` channel: No broker assigned (trades REJECTED)
- `jacob` channel: Risk enabled but no stop loss
- `jacob` channel: No broker assigned
- `pro-trader` channel: No broker assigned

### QQQ 716P Stuck on Webull
- Trade #330 (risk_auto_import) shows OPEN but original signal was already STC'd
- Webull still holds position — STC may have failed/rejected
- Source `risk_auto_import` is in _BLOCKED_SOURCES — risk engine won't auto-close
- Needs manual close on Webull or source override in DB
