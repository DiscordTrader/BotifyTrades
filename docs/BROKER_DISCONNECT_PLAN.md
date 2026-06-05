# Broker Disconnect Button — Implementation Plan

## Overview

Add a **Disconnect** button for every broker in **Admin → Settings → Brokers**, allowing users to cleanly disconnect a broker's live session without restarting the bot.

---

## Current State

### What exists today

| Component | Status |
|-----------|--------|
| `POST /api/brokers/disconnect/<broker_id>` route | **Exists but cosmetic** — only flips `BROKER_STATUS` flag, does NOT call the broker's real `disconnect()` |
| `async def disconnect()` on every broker class | **Fully implemented** for all 10 brokers |
| `BROKER_STATUS` dict in `broker_credentials_service.py` | Tracks in-memory connection state per broker_id |
| Frontend disconnect button | **Does not exist** in `brokers.html` or `settings.html` |

### Broker disconnect() methods (already implemented)

| Broker | File | What `disconnect()` does |
|--------|------|--------------------------|
| **Webull** | `src/brokers/webull_broker.py:276` | Stops streaming client, cancels token refresh task, clears option ID caches, sets `connected=False`, `_tokens_valid=False` |
| **Alpaca** | `src/brokers/alpaca_broker.py:128` | Nulls `trading_client` + `data_client`, sets `connected=False` |
| **Tastytrade** | `src/brokers/tastytrade_broker.py:234` | Nulls `session` + `account`, sets `connected=False` |
| **IBKR** | `src/brokers/ibkr_broker.py:114` | Calls `self.ib.disconnect()` if connected, sets `connected=False` |
| **Schwab** | `src/brokers/schwab_broker.py:703` | Nulls `access_token`, sets `connected=False` |
| **Robinhood** | `src/brokers/robinhood_broker.py:132` | Calls `rh.logout()` via `asyncio.to_thread`, sets `connected=False`, `_logged_in=False` |
| **Trading 212** | `src/brokers/trading212_broker.py:158` | Calls `await self._client.close()`, sets `connected=False` |
| **Zerodha** | `src/brokers/zerodha_broker.py:202` | Calls `kite.invalidate_access_token()`, nulls kite, sets `connected=False` |
| **Upstox** | `src/brokers/upstox_broker.py:145` | Nulls `api_client`, stops refresh scheduler, sets `connected=False` |
| **DhanQ** | `src/brokers/dhanq_broker.py:266` | Nulls `dhan` + `access_token`, sets `connected=False` |

### Broker ID → Instance mapping

```
broker_id              → _bot_instance attribute
─────────────────────────────────────────────────
webull_live            → .broker  (or .webull_broker)
webull_paper           → .paper_broker
alpaca_live            → .alpaca_live_broker
alpaca_paper           → .alpaca_paper_broker (or .paper_broker)
tastytrade_live        → .tastytrade_broker
tastytrade_paper       → .tastytrade_broker (paper_trade=True)
ibkr_live              → .ibkr_broker
ibkr_paper             → .ibkr_broker (paper_trade=True)
schwab                 → .schwab_broker
robinhood              → .robinhood_broker
trading212             → .trading212_broker
dhanq                  → .dhanq_broker
upstox                 → .upstox_broker
zerodha                → .zerodha_broker
```

---

## Risk Analysis: Will Disconnect Break Entry/Exit Flows?

### Safe — No impact on these flows

| Flow | Why it's safe |
|------|---------------|
| **New signal entries** | All broker `place_order()` methods check `if not self.connected` and return `OrderResult(success=False)` — signals fail fast, no partial fills |
| **Broker sync service** | `_perform_sync()` checks `getattr(broker_instance, 'connected', False)` and silently skips disconnected brokers |
| **Risk engine retry** | `position_monitor.py` has Extended Retry Mode — if exit fails, it enters cooldown with exponential backoff and retries when broker reconnects |
| **Order chaser** | Checks broker connection before chasing unfilled orders |
| **Broker-native resting orders** | Stop losses and limit orders already placed at the exchange (stocks on most brokers) continue to execute at broker side — they don't need the bot |

### Risky — These flows are affected

| Flow | Risk Level | Why |
|------|-----------|-----|
| **Bot-managed trailing stops** | HIGH | The bot actively updates SL price every tick. Disconnect = no more trailing. Position runs unprotected. |
| **Options local SL (Webull/RH)** | HIGH | Options stop losses on Webull and Robinhood are entirely bot-managed (local monitoring). Disconnect = no stop loss fires. |
| **Tastytrade options SL** | HIGH | TT doesn't support stop orders for options — bot uses limit-as-stop substitute. Disconnect = no exit protection. |
| **Price target cascades** | MEDIUM | Multi-target PT system (PT1→PT2→PT3) is bot-managed. Disconnect = cascades stop. |
| **GTC exit order monitoring** | MEDIUM | Risk engine monitors GTC exits and re-places if cancelled. Disconnect = no re-placement. |
| **Position reconciliation** | LOW | Broker may fill exits while disconnected, but app can't reconcile until reconnect. Stale OPEN records remain in DB. |

### Required safety gate

Before allowing disconnect, the API **must**:
1. Query open positions for that broker
2. If count > 0, return a warning: *"You have N open positions on this broker. Bot-managed stop losses and trailing stops will stop working. Are you sure?"*
3. Frontend shows confirmation dialog with the warning
4. User must explicitly confirm (or use a `force=true` flag)

---

## Implementation Plan

### Step 1: Backend — Fix disconnect route (routes.py)

**File:** `gui_app/routes.py` (line ~15850)

Replace the current cosmetic disconnect handler:

```python
# CURRENT (cosmetic only):
@app.route('/api/brokers/disconnect/<broker_id>', methods=['POST'])
def api_disconnect_broker(broker_id):
    try:
        from .broker_credentials_service import set_broker_status
        set_broker_status(broker_id, False, 'disconnected')
        return jsonify({
            'success': True,
            'message': f'{broker_id} disconnected',
            'status': 'disconnected'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
```

**Replace with:**

```python
@app.route('/api/brokers/disconnect/<broker_id>', methods=['POST'])
def api_disconnect_broker(broker_id):
    """Disconnect a broker — calls real disconnect() on the broker instance"""
    try:
        from .broker_credentials_service import set_broker_status
        import asyncio

        force = request.json.get('force', False) if request.is_json else False

        # Map broker_id to bot instance attribute
        BROKER_INSTANCE_MAP = {
            'webull_live': 'broker',
            'webull_paper': 'paper_broker',
            'alpaca_live': 'alpaca_live_broker',
            'alpaca_paper': 'alpaca_paper_broker',
            'tastytrade_live': 'tastytrade_broker',
            'tastytrade_paper': 'tastytrade_broker',
            'ibkr_live': 'ibkr_broker',
            'ibkr_paper': 'ibkr_broker',
            'schwab': 'schwab_broker',
            'robinhood': 'robinhood_broker',
            'trading212': 'trading212_broker',
            'dhanq': 'dhanq_broker',
            'upstox': 'upstox_broker',
            'zerodha': 'zerodha_broker',
        }

        attr_name = BROKER_INSTANCE_MAP.get(broker_id)
        broker_instance = None
        if attr_name and _bot_instance:
            broker_instance = getattr(_bot_instance, attr_name, None)

        # Safety check: count open positions for this broker
        open_count = 0
        if not force and broker_instance:
            try:
                from .database import get_connection
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM trades WHERE broker = ? AND status IN ('OPEN', 'PENDING')",
                    (broker_id,)
                )
                open_count = cursor.fetchone()[0] or 0
                conn.close()
            except Exception as count_err:
                print(f"[API] Could not count open positions: {count_err}")

        if open_count > 0 and not force:
            return jsonify({
                'success': False,
                'needs_confirmation': True,
                'open_positions': open_count,
                'warning': f'You have {open_count} open position(s) on {broker_id}. '
                           f'Bot-managed stop losses, trailing stops, and price target '
                           f'cascades will STOP working after disconnect. '
                           f'Broker-native resting orders (already placed at exchange) '
                           f'will continue to work.',
                'message': 'Confirm disconnect to proceed'
            })

        # Call real disconnect on the broker instance
        if broker_instance and hasattr(broker_instance, 'disconnect'):
            try:
                if _bot_instance and hasattr(_bot_instance, 'loop') and _bot_instance.loop:
                    future = asyncio.run_coroutine_threadsafe(
                        broker_instance.disconnect(),
                        _bot_instance.loop
                    )
                    future.result(timeout=10)
                else:
                    loop = asyncio.new_event_loop()
                    try:
                        loop.run_until_complete(broker_instance.disconnect())
                    finally:
                        loop.close()
                print(f"[API] ✓ {broker_id} disconnect() called successfully")
            except Exception as disc_err:
                print(f"[API] ⚠️ {broker_id} disconnect() error: {disc_err}")
                # Still update status even if disconnect() had issues

        # Update centralized status
        set_broker_status(broker_id, False, 'disconnected')

        # Notify health monitor
        try:
            from .broker_health_monitor import get_health_monitor
            hm = get_health_monitor()
            if hm:
                hm.record_disconnection(broker_id, 'User initiated disconnect')
        except Exception:
            pass

        # Discord notification
        try:
            from .discord_notifier import notify_broker_disconnected
            display_name = broker_id.replace('_', ' ').title()
            notify_broker_disconnected(display_name, 'User initiated disconnect from GUI')
        except Exception:
            pass

        return jsonify({
            'success': True,
            'message': f'{broker_id} disconnected successfully',
            'status': 'disconnected',
            'had_open_positions': open_count
        })

    except Exception as e:
        print(f"[API] Error disconnecting broker {broker_id}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
```

### Step 2: Frontend — Add disconnect button (brokers.html)

**File:** `gui_app/templates/brokers.html`

Add a Disconnect button next to each broker's Connect button. Only show when broker is connected.

```html
<!-- In each broker card, next to the Connect button -->
<button class="btn btn-outline-danger btn-sm disconnect-broker-btn"
        data-broker-id="${brokerId}"
        style="display: none;"
        onclick="disconnectBroker('${brokerId}')">
    <i class="fas fa-unlink"></i> Disconnect
</button>
```

```javascript
async function disconnectBroker(brokerId) {
    // First call without force to check for open positions
    try {
        const response = await fetch(`/api/brokers/disconnect/${brokerId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force: false })
        });
        const data = await response.json();

        if (data.needs_confirmation) {
            // Show confirmation dialog with position warning
            const confirmed = confirm(
                `⚠️ WARNING: ${data.warning}\n\n` +
                `Do you want to disconnect anyway?`
            );
            if (!confirmed) return;

            // Re-call with force=true
            const forceResponse = await fetch(`/api/brokers/disconnect/${brokerId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ force: true })
            });
            const forceData = await forceResponse.json();
            if (forceData.success) {
                showToast(`${brokerId} disconnected`, 'success');
                refreshBrokerStatus();
            } else {
                showToast(`Disconnect failed: ${forceData.error}`, 'error');
            }
        } else if (data.success) {
            showToast(`${brokerId} disconnected`, 'success');
            refreshBrokerStatus();
        } else {
            showToast(`Disconnect failed: ${data.error}`, 'error');
        }
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}
```

**Show/hide logic** in the existing `refreshBrokerStatus()`:

```javascript
// Inside the status refresh loop, for each broker card:
const disconnectBtn = card.querySelector('.disconnect-broker-btn');
if (disconnectBtn) {
    disconnectBtn.style.display = isConnected ? 'inline-block' : 'none';
}
```

### Step 3: Schwab special handling

Schwab has a separate auth flow (`/schwab/callback` OAuth). Its disconnect should also clean up token files:

```python
# Inside the disconnect handler, add Schwab-specific cleanup:
if broker_id == 'schwab' and broker_instance:
    try:
        from .schwab_auth import cleanup_schwab_tokens
        cleanup_schwab_tokens()
    except Exception:
        pass
```

This aligns with the existing `/schwab/disconnect` route behavior.

---

## Effort Estimate

| Task | Time |
|------|------|
| Fix backend disconnect route (real `disconnect()` call + safety gate) | 2-3 hours |
| Add frontend disconnect button + confirmation dialog | 2-3 hours |
| Show/hide logic tied to broker status refresh | 1 hour |
| Schwab token cleanup alignment | 30 min |
| Testing all 10 broker disconnect flows | 2-3 hours |
| **Total** | **~1-1.5 days** |

---

## Testing Checklist

- [ ] Disconnect button appears only for connected brokers
- [ ] Disconnect button hidden for disconnected brokers
- [ ] Safety warning appears when broker has open positions
- [ ] Confirmation required before disconnecting with open positions
- [ ] Force disconnect works after confirmation
- [ ] Broker instance `connected` flag is `False` after disconnect
- [ ] Broker session/tokens are properly cleaned up
- [ ] `BROKER_STATUS` dict reflects disconnected state
- [ ] Health monitor records the disconnection
- [ ] Discord notification fires on disconnect
- [ ] Broker sync service skips disconnected broker on next cycle
- [ ] Risk engine handles disconnected broker gracefully (retry mode)
- [ ] Reconnect works after disconnect (Connect button still functional)
- [ ] Webull streaming client stops on disconnect
- [ ] IBKR TWS connection closes on disconnect
- [ ] Schwab tokens cleaned up on disconnect
- [ ] Robinhood `rh.logout()` called on disconnect

---

## Files Modified

| File | Change |
|------|--------|
| `gui_app/routes.py` | Replace cosmetic disconnect handler with real implementation |
| `gui_app/templates/brokers.html` | Add disconnect button + JS handler |
| `gui_app/templates/settings.html` | Add disconnect button to broker status banner (optional) |

No changes needed to:
- Any broker class (disconnect methods already complete)
- `position_monitor.py` (already handles disconnected brokers)
- `broker_sync_service.py` (already skips disconnected brokers)
- `broker_credentials_service.py` (set_broker_status already works)
