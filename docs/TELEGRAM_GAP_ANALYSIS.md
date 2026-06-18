# Telegram Pipeline Gap Analysis
**Date:** 2026-06-17  
**Version:** v12.1.4  

---

## Architecture Overview

```
Telethon event loop (dedicated thread)
        │
        ▼
TelegramListener._submit_signal_to_queue()
        │  thread-safe queue.Queue (_telegram_signal_queue)
        ▼
telegram_signal_bridge() asyncio task  ← polls every 100ms
        │
        ├─ [market == 'INDIA' AND _conditional_order]
        │         └──► _route_telegram_conditional_order()
        │                        └──► conditional_order_router.create_order()
        │
        └─ [everything else]
                  └──► order_queue.put(signal)
                              └──► worker → position_monitor (same as Discord)
```

### Signal Parsing (registered at selfbot_webull.py:22806)

| Parser | Function | Handles |
|--------|----------|---------|
| `option_signal` | `parse_option_signal` | `BTO/STC [QTY] SYMBOL STRIKE C/P MM/DD @ PRICE` + conditional triggers |
| `stock_signal` | `parse_stock_signal` | `BTO/STC [QTY] SYMBOL @ PRICE` |
| `india_option_signal` | `parse_india_option_signal` | `BUY NIFTY 24000 CE @ 145`, ABOVE/SL/TGT variants |
| `india_stock_signal` | `parse_india_stock_signal` | India equity format |

### Risk Engine Wiring

- `position_monitor.py` SQL JOIN at line 374 includes `telegram_chat_id` column:
  ```sql
  WHERE discord_channel_id = ? OR CAST(id AS TEXT) = ? OR telegram_chat_id = ?
  ```
- Same PT/SL/trailing bracket logic applies to Telegram positions — risk engine is platform-agnostic.
- DB schema: channels table stores `platform='telegram'`, `discord_channel_id = 'tg_{chat_id}'`, `telegram_chat_id = {chat_id}`.

---

## What Works Correctly

| Feature | Status | Notes |
|---------|--------|-------|
| US stock entry (BTO) | ✅ Working | parse_stock_signal → order_queue |
| US option entry (BTO) | ✅ Working | parse_option_signal → order_queue |
| US stock/option exit (STC) | ✅ Working | order_queue → worker |
| India option conditional order | ✅ Working | _route_telegram_conditional_order → conditional_order_router |
| India stock conditional order | ✅ Working | Same path |
| Risk engine PT/SL brackets | ✅ Working | telegram_chat_id JOIN in position_monitor |
| Exit strategy mode='risk' block | ✅ Working | Bridge line 19651 guards STC when exit_strategy_mode='risk' |
| Circuit breaker check | ✅ Working | Bridge checks is_circuit_breaker_tripped() before BTO/BTC |
| Signal tracking (lots/DB) | ✅ Working | listener.py _save_signal_for_tracking() uses same lot system as Discord |

---

## Gap 1 — US Conditional Orders Bypass conditional_order_router (HIGH)

### Root Cause

`telegram_signal_bridge` line 19646:
```python
if signal.get('_conditional_order') and signal.get('market') == 'INDIA':
    await self._route_telegram_conditional_order(signal)
else:
    await self.order_queue.put(signal)   # ← US conditional triggers land here
```

When `parse_option_signal` detects a US conditional trigger (e.g., `BTO SPY 450C 6/21 ABOVE 452`), it sets:
- `signal['_conditional_order'] = True`
- `signal['trigger_price'] = 452`
- `signal['trigger_condition'] = 'above'`

The `market` field is `None` or `'US'`, so the India guard is False. The signal goes directly to `order_queue` and executes **immediately at market**, ignoring the trigger price entirely.

### Impact

Any US conditional trigger from Telegram executes as an immediate market order. The conditional_order_router (which monitors price and waits for trigger) is never called. This is a silent behavioral difference from Discord, where the same signal format correctly creates a conditional order.

### Fix

Extend the routing condition to also route US conditional orders:
```python
if signal.get('_conditional_order'):
    market = signal.get('market', '').upper()
    if market == 'INDIA':
        await self._route_telegram_conditional_order(signal)
    else:
        # US conditional — route to conditional_order_router directly
        try:
            from src.services.conditional_orders.router import conditional_order_router
            channel_id = signal.get('channel_id') or signal.get('discord_channel_id', '')
            await conditional_order_router.create_order(signal, channel_id)
            print(f"[TELEGRAM BRIDGE] ✓ US conditional order created: {signal.get('symbol')} trigger={signal.get('trigger_price')}")
        except Exception as e:
            print(f"[TELEGRAM BRIDGE] ⚠️ Conditional order routing failed, falling back to direct: {e}")
            await self.order_queue.put(signal)
else:
    await self.order_queue.put(signal)
```

---

## Gap 2 — Only 4 Parsers Registered (MEDIUM)

### Root Cause

selfbot_webull.py `run_telegram_bot_thread()` registers only the base parsers (lines 22806-22810). The `signal_format_registry` (Phoenix, ProTrader, Eagle, ABTrades, Viking, ZZ formats) is NOT wired into the Telegram listener.

Discord path calls `parse_with_registry()` at lines 14626 and 15362 for channels that have these formats configured. Telegram listener.py calls its own registered parsers only — no registry integration.

### Impact

Telegram channels using advanced signal formats (Phoenix alerts, ProTrader, Eagle scanner, ABTrades) will fail to parse or produce no signal. The message will silently drop.

Currently affects: any Telegram group posting signals in a registry-registered format.

### Scope of Signal Formats Missing from Telegram

| Registry Format Group | Example Pattern | Telegram Impact |
|-----------------------|----------------|-----------------|
| Phoenix alerts | `SELL NIFTY 24000 CE @ 142 (SL: 155)` (stock variant with metadata) | Not parsed |
| ProTrader | `ProTrader: BUY XYZ ...` | Not parsed |
| Eagle scanner | Structured embed-like text blocks | Not parsed |
| ABTrades | Format-specific option notation | Not parsed |
| Viking | Multi-line structured alerts | Not parsed |

**Note:** Equity Genie format relies on Discord embed structure (`title`, `description` fields) which is never present in Telegram messages — `TelegramMessage.embeds = []` always. This is a by-design limitation, not a bug.

### Fix Option A — Channel-level format override

In `listener.py`, after parsing with the 4 base parsers, if all return `None`, call `parse_with_registry()` using the channel's configured format:
```python
from src.services.signal_format_registry import parse_with_registry
result = parse_with_registry(message_text, channel_config)
```

### Fix Option B — Per-channel parser registration

Extend `register_parser()` to support channel-scoped parsers, set during Telegram channel configuration.

---

## Gap 3 — `_risk_management` Dict Is Dead Code (LOW)

### Root Cause

`listener.py` `_process_signal()` (lines 487-496) builds a `_risk_management` dict on every signal:
```python
signal['_risk_management'] = {
    'channel_id': channel_id,
    'position_size_pct': ...,
    'stop_loss_pct': ...,
    ...
}
```

A full `grep` of `selfbot_webull.py` shows **zero reads** of `signal['_risk_management']` or `signal.get('_risk_management')`. Risk settings are applied via DB JOIN in `position_monitor.py`, not via this dict.

### Impact

None — risk management works correctly via position_monitor SQL. The dict wastes a small amount of memory per signal.

### Fix

Remove the `_risk_management` dict construction in `listener.py` `_process_signal()`. No downstream changes needed.

---

## Gap 4 — No Embed Content (By Design)

### Root Cause

Telegram has no Discord-style rich embeds. `TelegramMessage.embeds` is hardcoded to `[]` in `listener.py`. Parsers that gate on embed presence (Equity Genie's `is_equity_genie_embed()`, which checks `message.embeds[0].title`) will always return `None` for Telegram messages.

### Impact

Equity Genie signals **cannot work on Telegram** by design. The channel broadcasts via Discord embeds — the formatting is intrinsic to how the signal carries structured data (ticker, PTs, SLs in embed fields/description).

### Resolution

No fix needed. Document: Equity Genie and any other embed-dependent parsers are Discord-only. Telegram channels that want multi-ticker bracket signals must use a text-based format compatible with the registered parsers.

---

## Summary Table

| Gap | Severity | Affects | Fix Complexity |
|-----|----------|---------|----------------|
| G1: US conditional orders bypass router | HIGH | Any US trigger-price signal from Telegram | Low — 15 lines in telegram_signal_bridge |
| G2: Only 4 parsers registered | MEDIUM | Telegram channels using Phoenix/ProTrader/etc | Medium — registry integration in listener |
| G3: `_risk_management` dead code | LOW | None (no runtime impact) | Trivial — delete 10 lines in listener.py |
| G4: No embeds | By design | Equity Genie format | N/A — not a bug |

---

## DB Schema Reference

```sql
-- channels table (relevant Telegram fields)
telegram_chat_id    TEXT   -- raw chat id (e.g. -1001234567890)
platform            TEXT   -- 'telegram' or 'discord'
discord_channel_id  TEXT   -- set to 'tg_{chat_id}' for telegram channels

-- telegram_settings table (singleton id=1)
enabled       INTEGER
api_id        TEXT
api_hash      TEXT
phone_number  TEXT
session_string TEXT
```

`get_channel_by_telegram_id()` in `database.py` (line 8476) strips the `-100` prefix and looks up by `telegram_chat_id OR telegram_username OR stripped_id`.

---

## Related Files

| File | Lines | Purpose |
|------|-------|---------|
| [src/telegram_client/listener.py](../src/telegram_client/listener.py) | ~500 | Telethon listener, parser dispatch, queue submit |
| [src/selfbot_webull.py](../src/selfbot_webull.py#L19611) | 19611-19668 | telegram_signal_bridge asyncio task |
| [src/selfbot_webull.py](../src/selfbot_webull.py#L19669) | 19669+ | _route_telegram_conditional_order (India only) |
| [src/selfbot_webull.py](../src/selfbot_webull.py#L22756) | 22756 | run_telegram_bot_thread + parser registration |
| [src/risk/position_monitor.py](../src/risk/position_monitor.py#L374) | 374-376 | telegram_chat_id JOIN in risk SQL |
| [gui_app/database.py](../gui_app/database.py#L8431) | 8431-8476 | Telegram channel DB operations |
