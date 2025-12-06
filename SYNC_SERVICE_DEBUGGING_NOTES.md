# Broker Sync Service - Debugging Notes

## Current Status

**ISSUE**: The broker sync service is initialized and the async task is created, but the `_sync_loop()` coroutine never executes.

### What Works ✅
- Service initialization: `[SYNC] Initializing trade synchronization service...`
- Task creation: `await self.sync_service.start()` completes without error
- Print statements are now using `flush=True` for immediate output
- All logger calls replaced with print() calls

### What Doesn't Work ❌
- The `_sync_loop()` coroutine never executes (no "[SYNC] 🔄 Sync loop started" message)
- No sync cycles are running (no "[SYNC] 🔄 Starting sync cycle" messages)
- Expired positions (BIDU 11/21) remain as OPEN instead of being closed

## Root Cause Analysis

The async task is created but never scheduled/executed by the event loop. Possible causes:

1. **Event Loop Contention**: The Discord bot's event loop is busy with other tasks
2. **Task Priority**: The sync task has no mechanism to ensure it gets CPU time
3. **Silent Exception**: An exception in `_sync_loop()` is being swallowed
4. **Asyncio Scheduling Issue**: The task needs explicit scheduling with `await asyncio.sleep(0)`

## Attempted Fixes

1. ✅ Replaced `logger.info()` with `print()` (logging not configured)
2. ✅ Added `flush=True` to all print statements
3. ✅ Added `await asyncio.sleep(0)` after task creation
4. ❌ Task still doesn't execute

## Next Steps for Debugging

### 1. Add Exception Handling to Task Creation
```python
async def start(self):
    self.running = True
    try:
        self._task = asyncio.create_task(self._sync_loop())
        # Force immediate scheduling
        await asyncio.sleep(0.1)  # Give task time to start
        print(f"[SYNC] Task status: {self._task}")
    except Exception as e:
        print(f"[SYNC] Task creation failed: {e}")
        traceback.print_exc()
```

### 2. Add Heartbeat to Sync Loop
```python
async def _sync_loop(self):
    print("[SYNC] 🔄 Sync loop started", flush=True)
    iteration = 0
    while self.running:
        try:
            print(f"[SYNC] Heartbeat {iteration}", flush=True)
            iteration += 1
            await asyncio.sleep(self.sync_interval)
            await self._perform_sync()
        except Exception as e:
            print(f"[SYNC] Loop error: {e}", flush=True)
            traceback.print_exc()
```

### 3. Use asyncio.ensure_future() Instead of create_task()
```python
self._task = asyncio.ensure_future(self._sync_loop())
```

### 4. Add Task Monitoring
```python
# After creating task, monitor it
async def monitor_sync_task():
    while True:
        await asyncio.sleep(10)
        if self.sync_service._task:
            print(f"[SYNC] Task status: done={self.sync_service._task.done()}, cancelled={self.sync_service._task.cancelled()}")

asyncio.create_task(monitor_sync_task())
```

## Temporary Workaround

Until the async scheduling issue is resolved, use SQL to manually manage expired/closed positions:

```sql
-- Close expired positions
UPDATE trades 
SET status = 'CLOSED', 
    close_reason = 'EXPIRED', 
    closed_at = datetime('now')
WHERE status = 'OPEN' 
  AND expiry < date('now') 
  AND broker = 'Webull';
```

## Files Modified

- `broker_sync_service.py`: All logger calls replaced with print(flush=True)
- `src/selfbot_webull.py`: Added yield to event loop after sync service start

## Date

2025-11-24
