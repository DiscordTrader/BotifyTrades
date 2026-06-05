# 🔍 Complete Gap Analysis: WaxUI, C1apped, Risk Management & Conditional Orders

## Industry-Standard Implementation Plan for BotifyTrades

---

## EXECUTIVE SUMMARY

| Component | Current State | Gaps Found | Priority | Breaking Risk |
|-----------|---------------|------------|----------|---------------|
| **🚨 C1apped Message Edit** | **NO on_message_edit handler** | **CRITICAL** | **P0** | **Low** |
| **WaxUI Parsing** | Entry/Trim/Close only | 7 major gaps | P0 | Low |
| **C1apped/TRADE IDEA** | Basic parsing | 6 major gaps | P0 | Medium |
| **Risk Management** | Settings stored, not enforced | 9 major gaps | P0 | Medium |
| **Conditional Orders** | Basic monitoring | 5 major gaps | P1 | Medium |
| **Trailing Stop** | Column exists, not executed | 4 major gaps | P0 | Medium |

---

## 🚨 CRITICAL GAP: Discord Message Edit Handling

### The Problem (From Screenshots)

C1apped signals are **Discord embeds that get EDITED** - they don't post new messages for updates:

| Time | What Happens | SL | Levels | Current Handling |
|------|--------------|------|--------|------------------|
| 8:15 AM | **Original post** | 1.09 | 1.26 - 1.29 - 1.33 - 1.38+ | ✅ Processed by on_message |
| 8:39 AM | **EDIT: PT1 hit** | 1.09 | ~~1.26~~ - 1.29 - 1.33 - 1.38+ | ❌ MISSED (no edit handler) |
| 8:43 AM | **EDIT: SL raised** | **1.19** | ~~1.26~~ - 1.29 - 1.33 - 1.38+ | ❌ MISSED (no edit handler) |
| Later | **EDIT: All out** | 1.19 | ~~1.26~~ | ❌ MISSED (no edit handler) |

### Why This Is Critical

1. **SL changes are NEVER propagated to broker** - User's broker SL stays at 1.09 even when trader raises to 1.19
2. **PT hits are NEVER detected** - Can't trigger partial exits
3. **Exit signals are MISSED** - "All out" never triggers STC
4. **The entire dynamic signal flow is broken**

### Current Code Evidence

```bash
$ grep -n "on_message_edit" src/selfbot_webull.py
(no results)  # ← NO EDIT HANDLER EXISTS
```

### Complete Implementation Required

#### Step 1: Add Message ID to Database

```sql
-- File: gui_app/database.py - Add to signal_instances table

ALTER TABLE signal_instances ADD COLUMN discord_message_id TEXT;
ALTER TABLE signal_instances ADD COLUMN discord_channel_id TEXT;
CREATE INDEX idx_signal_instances_message_id ON signal_instances(discord_message_id);
```

```python
# Python migration in gui_app/database.py
signal_instance_new_columns = [
    ('discord_message_id', 'TEXT'),
    ('discord_channel_id', 'TEXT'),
    ('original_sl', 'REAL'),  # Store original SL for comparison
    ('current_sl', 'REAL'),   # Track current SL (may differ from original)
    ('hit_level_count', 'INTEGER DEFAULT 0'),  # Track how many PTs hit
]
```

#### Step 2: Store Message ID on Original Signal

```python
# File: src/selfbot_webull.py - In signal processing (~line 8200)

# After successfully processing a TRADE IDEA signal:
if trade_idea and instance_id:
    # Store Discord message metadata for edit tracking
    update_signal_instance(instance_id, {
        'discord_message_id': str(message.id),
        'discord_channel_id': str(message.channel.id),
        'original_sl': trade_idea.get('stop_loss'),
        'current_sl': trade_idea.get('stop_loss'),
        'hit_level_count': len(trade_idea.get('hit_levels', []))
    })
    print(f"[TRADE IDEA] Stored message_id={message.id} for edit tracking")
```

#### Step 3: Add on_message_edit Handler (THE CRITICAL FIX)

```python
# File: src/selfbot_webull.py - Add after on_message handler

@client.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    """
    Handle Discord message edits for C1apped/TRADE IDEA signals.
    
    C1apped traders EDIT their Discord embeds to:
    1. Strike through hit profit targets (~~1.26~~)
    2. Raise stop loss (SL: 1.09 -> SL: 1.19)
    3. Post exit signals ("All out here")
    
    This handler detects these changes and propagates them to the broker.
    """
    try:
        # Skip if not from a tracked channel
        channel_id = str(after.channel.id)
        channel_info = get_channel_info(channel_id)
        if not channel_info or not channel_info.get('enabled'):
            return
        
        # Skip bot messages, DMs, etc.
        if after.author.bot:
            return
        
        # Extract embed content (C1apped uses embeds)
        embed_content_parts = []
        if hasattr(after, 'embeds') and after.embeds:
            for embed in after.embeds:
                if embed.title:
                    embed_content_parts.append(embed.title)
                if embed.description:
                    embed_content_parts.append(embed.description)
                for field in embed.fields:
                    embed_content_parts.append(f"{field.name}: {field.value}")
        
        combined_content = after.content + "\n" + "\n".join(embed_content_parts)
        
        # Check if this is a TRADE IDEA signal
        from src.signals.parser import is_trade_idea_signal, parse_trade_idea
        
        if not is_trade_idea_signal(combined_content):
            return
        
        # Look up existing signal instance by message_id
        message_id = str(after.id)
        existing_instance = get_signal_instance_by_message_id(message_id)
        
        if not existing_instance:
            # This edit is for a message we didn't track (e.g., from before bot started)
            print(f"[MESSAGE EDIT] No tracked instance for message_id={message_id}")
            return
        
        # Reparse the edited message
        parsed = parse_trade_idea(combined_content)
        if not parsed:
            return
        
        print(f"[MESSAGE EDIT] Detected edit for {parsed['ticker']} (instance={existing_instance['id']})")
        
        # Compare SL: Did it change?
        old_sl = existing_instance.get('current_sl') or existing_instance.get('original_sl')
        new_sl = parsed.get('stop_loss')
        
        sl_changed = False
        if new_sl and old_sl and abs(new_sl - old_sl) > 0.001:
            sl_changed = True
            sl_direction = "RAISED" if new_sl > old_sl else "LOWERED"
            print(f"[MESSAGE EDIT] 📈 SL {sl_direction}: ${old_sl} -> ${new_sl}")
        
        # Compare hit levels: Did new targets get hit?
        old_hit_count = existing_instance.get('hit_level_count', 0)
        new_hit_count = len(parsed.get('hit_levels', []))
        
        new_hits = False
        if new_hit_count > old_hit_count:
            new_hits = True
            print(f"[MESSAGE EDIT] 🎯 New PT hit! {old_hit_count} -> {new_hit_count}")
        
        # Check for exit signal
        is_exit = parsed.get('is_exit', False)
        if is_exit:
            print(f"[MESSAGE EDIT] 🚪 EXIT SIGNAL detected: All out")
        
        # Get exit strategy mode for this channel
        exit_strategy_mode = channel_info.get('exit_strategy_mode', 'signal')
        
        # Route changes through SignalExitManager
        if get_feature_flag('enable_signal_exit_manager'):
            from src.services.signal_exit_manager import signal_exit_manager
            from src.services.exit_order_arbiter import exit_order_arbiter
            
            if sl_changed and exit_strategy_mode in ['signal', 'hybrid']:
                # Request SL update through arbiter
                arbiter_result = await exit_order_arbiter.request_sl_update(
                    signal_instance_id=existing_instance['id'],
                    source='signal',
                    new_sl_price=new_sl,
                    current_sl_price=old_sl,
                    exit_strategy_mode=exit_strategy_mode
                )
                
                if arbiter_result['approved']:
                    # Execute SL update
                    sl_result = await signal_exit_manager.handle_sl_update(
                        signal_instance_id=existing_instance['id'],
                        new_sl_price=new_sl,
                        exit_strategy_mode=exit_strategy_mode,
                        source='signal_edit'
                    )
                    print(f"[MESSAGE EDIT] ✅ SL update sent to broker: {sl_result}")
            
            if new_hits:
                # Trigger partial exit for new PT hits
                pt_result = await signal_exit_manager.handle_pt_hit(
                    signal_instance_id=existing_instance['id'],
                    hit_level_index=new_hit_count,
                    current_price=parsed.get('hit_levels', [])[-1] if parsed.get('hit_levels') else None
                )
                print(f"[MESSAGE EDIT] ✅ PT hit processed: {pt_result}")
            
            if is_exit:
                # Trigger full exit
                exit_result = await signal_exit_manager.handle_exit_signal(
                    signal_instance_id=existing_instance['id'],
                    exit_type='signal',
                    reason='Trader posted exit signal'
                )
                print(f"[MESSAGE EDIT] ✅ Exit executed: {exit_result}")
        else:
            # Feature flag off - just log the changes
            print(f"[MESSAGE EDIT] Changes detected but SignalExitManager disabled")
        
        # Update stored values
        update_signal_instance(existing_instance['id'], {
            'current_sl': new_sl if new_sl else old_sl,
            'hit_level_count': new_hit_count,
        })
        
    except Exception as e:
        print(f"[MESSAGE EDIT] Error processing edit: {e}")
        import traceback
        traceback.print_exc()
```

#### Step 4: Database Helper Functions

```python
# File: gui_app/database.py - Add these functions

def get_signal_instance_by_message_id(message_id: str) -> Optional[Dict]:
    """Look up signal instance by Discord message ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM signal_instances 
        WHERE discord_message_id = ? AND status = 'open'
        ORDER BY created_at DESC LIMIT 1
    ''', (message_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    return None


def update_signal_instance_sl(instance_id: int, new_sl: float, source: str = 'signal'):
    """Update the current stop loss for a signal instance."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE signal_instances 
        SET current_sl = ?, updated_at = ?, sl_update_source = ?
        WHERE id = ?
    ''', (new_sl, datetime.now().isoformat(), source, instance_id))
    conn.commit()
    conn.close()
```

### Debouncing Rapid Edits

C1apped may make multiple quick edits. Add debouncing to prevent broker API flooding:

```python
# File: src/services/signal_exit_manager.py

from collections import defaultdict
from datetime import datetime, timedelta
import asyncio

class EditDebouncer:
    """Debounce rapid message edits to prevent broker API flooding."""
    
    def __init__(self, debounce_ms: int = 100):
        self.debounce_ms = debounce_ms
        self._pending = {}  # message_id -> (task, latest_data)
    
    async def debounce(self, message_id: str, callback, *args, **kwargs):
        """Debounce a callback for the given message."""
        
        # Cancel any pending task for this message
        if message_id in self._pending:
            old_task, _ = self._pending[message_id]
            old_task.cancel()
        
        # Create new debounced task
        async def delayed_call():
            await asyncio.sleep(self.debounce_ms / 1000)
            del self._pending[message_id]
            await callback(*args, **kwargs)
        
        task = asyncio.create_task(delayed_call())
        self._pending[message_id] = (task, kwargs)


# Global debouncer
edit_debouncer = EditDebouncer(debounce_ms=100)
```

### Updated on_message_edit with Debouncing

```python
@client.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    # ... (channel checks as above) ...
    
    # Debounce to handle rapid edits
    from src.services.signal_exit_manager import edit_debouncer
    
    await edit_debouncer.debounce(
        message_id=str(after.id),
        callback=process_trade_idea_edit,
        after=after,
        channel_info=channel_info
    )
```

### Testing the Edit Handler

```python
# Test cases for on_message_edit:

# Test 1: SL Raised
# Before: SL: 1.09 | After: SL: 1.19
# Expected: Broker SL modified from 1.09 to 1.19

# Test 2: PT Hit (Strikethrough)
# Before: Levels: 1.26 - 1.29 | After: Levels: ~~1.26~~ - 1.29
# Expected: Partial exit triggered for first PT

# Test 3: Exit Signal
# Before: (normal signal) | After: "All out here"
# Expected: Full exit triggered

# Test 4: Rapid Edits
# 3 edits within 50ms
# Expected: Only final state processed after 100ms debounce
```

---

## 🔒 CONFLICT RESOLUTION & INDUSTRY-GRADE REQUIREMENTS

### Architect Review Findings

The initial on_message_edit implementation has **critical gaps** that must be addressed:

| Issue | Risk Level | Status |
|-------|------------|--------|
| Exit strategy arbitration undefined | HIGH | ❌ Missing |
| Double-exit duplication | HIGH | ❌ Missing |
| PT quantity desync | MEDIUM | ❌ Missing |
| Conditional order sync | MEDIUM | ❌ Missing |
| Audit logging | MEDIUM | ❌ Missing |
| Rate limiting per broker | MEDIUM | ❌ Missing |
| Retry/rollback on failure | MEDIUM | ❌ Missing |
| Concurrent SL writer locking | HIGH | ❌ Missing |

### Conflict 1: Exit Strategy Mode Arbitration

**Problem**: In hybrid mode, trader raises SL to 1.19 but trailing stop calculates 1.15. Which wins?

**Resolution - Precedence Matrix**:

```python
# File: src/services/exit_order_arbiter.py

class ExitOrderArbiter:
    """
    Arbitrates between signal-driven and risk-driven exit requests.
    
    Precedence Rules:
    1. Manual override > All (user can always force exit)
    2. In SIGNAL mode: Signal SL always wins
    3. In RISK mode: Trailing/channel SL always wins
    4. In HYBRID mode: TIGHTER (higher for long, lower for short) SL wins
    5. CRITICAL: SL can NEVER be lowered in hybrid mode (only raised)
    """
    
    PRECEDENCE_MATRIX = {
        'signal': {
            'signal_sl': 100,      # Signal SL always wins
            'trailing_sl': 0,      # Ignored
            'channel_sl': 0,       # Ignored
            'manual': 999,         # Manual override highest
        },
        'risk': {
            'signal_sl': 0,        # Ignored
            'trailing_sl': 100,    # Trailing wins over channel
            'channel_sl': 50,      # Channel is fallback
            'manual': 999,         # Manual override highest
        },
        'hybrid': {
            'signal_sl': 100,      # Both considered
            'trailing_sl': 100,    # Both considered
            'channel_sl': 50,      # Fallback
            'manual': 999,         # Manual override highest
        }
    }
    
    async def request_sl_update(
        self,
        signal_instance_id: int,
        source: str,  # 'signal', 'trailing', 'channel', 'manual'
        new_sl_price: float,
        current_sl_price: float,
        exit_strategy_mode: str,
        position_direction: str = 'long'
    ) -> Dict:
        """
        Request an SL update. Returns approval status and final SL.
        
        Returns:
            {
                'approved': bool,
                'final_sl': float,
                'reason': str,
                'source_used': str
            }
        """
        # Rule 1: Manual override always wins
        if source == 'manual':
            return {
                'approved': True,
                'final_sl': new_sl_price,
                'reason': 'Manual override',
                'source_used': 'manual'
            }
        
        # Rule 2: Check mode-specific precedence
        if exit_strategy_mode == 'signal' and source != 'signal':
            return {
                'approved': False,
                'final_sl': current_sl_price,
                'reason': f'Signal mode: {source} SL ignored',
                'source_used': None
            }
        
        if exit_strategy_mode == 'risk' and source == 'signal':
            return {
                'approved': False,
                'final_sl': current_sl_price,
                'reason': 'Risk mode: signal SL ignored',
                'source_used': None
            }
        
        # Rule 3: HYBRID MODE - Use TIGHTER SL
        if exit_strategy_mode == 'hybrid':
            # For long positions: higher SL is tighter
            # For short positions: lower SL is tighter
            if position_direction == 'long':
                is_tighter = new_sl_price > current_sl_price
            else:
                is_tighter = new_sl_price < current_sl_price
            
            if not is_tighter:
                return {
                    'approved': False,
                    'final_sl': current_sl_price,
                    'reason': f'Hybrid mode: {source} SL not tighter than current',
                    'source_used': None
                }
        
        # Rule 4: NEVER lower SL (only raise for longs)
        if position_direction == 'long' and new_sl_price < current_sl_price:
            return {
                'approved': False,
                'final_sl': current_sl_price,
                'reason': 'SL cannot be lowered for long position',
                'source_used': None
            }
        
        # Approved
        return {
            'approved': True,
            'final_sl': new_sl_price,
            'reason': f'{source} SL approved',
            'source_used': source
        }
```

### Conflict 2: Double-Exit Prevention (Idempotency)

**Problem**: on_message STC parsing AND on_message_edit "All out" could both trigger exits.

**Resolution - Idempotency with processed_state**:

```python
# File: gui_app/database.py - Add columns

signal_instance_idempotency_columns = [
    ('exit_processed', 'INTEGER DEFAULT 0'),  # 1 = already exited
    ('exit_processed_at', 'TEXT'),
    ('exit_source', 'TEXT'),  # 'on_message', 'on_message_edit', 'trailing', 'manual'
    ('last_processed_edit_id', 'TEXT'),  # Prevent reprocessing same edit
]

# File: src/services/signal_exit_manager.py

class SignalExitManager:
    async def handle_exit_signal(
        self,
        signal_instance_id: int,
        exit_type: str,
        reason: str,
        source: str = 'signal'
    ) -> Dict:
        """Handle exit with idempotency check."""
        
        # Check if already exited
        instance = get_signal_instance(signal_instance_id)
        if instance.get('exit_processed'):
            return {
                'success': False,
                'reason': f"Already exited via {instance.get('exit_source')} at {instance.get('exit_processed_at')}",
                'skipped': True
            }
        
        # Mark as processing BEFORE broker call (optimistic lock)
        mark_exit_processing(signal_instance_id, source)
        
        try:
            # Execute broker exit
            result = await self._execute_broker_exit(instance)
            
            # Mark as completed
            mark_exit_completed(signal_instance_id, source)
            
            return {'success': True, 'broker_result': result}
            
        except Exception as e:
            # Rollback processing state
            rollback_exit_processing(signal_instance_id)
            raise
```

### Conflict 3: PT Quantity Synchronization

**Problem**: Signal says PT1 hit, but channel has profit_target_qty_1 = 25% configured.

**Resolution - Reconcile signal PT with channel settings**:

```python
# File: src/services/signal_exit_manager.py

async def handle_pt_hit(
    self,
    signal_instance_id: int,
    hit_level_index: int,  # 1-based: which PT was hit
    signal_exit_price: float = None
) -> Dict:
    """
    Handle profit target hit from signal.
    
    Reconciliation:
    1. Signal indicates PT1 hit (strikethrough)
    2. Look up channel's profit_target_qty_1 setting
    3. Execute trim of that quantity at market/limit
    4. Update remaining_qty in signal_instances
    """
    instance = get_signal_instance(signal_instance_id)
    channel_info = get_channel_info(instance['channel_id'])
    
    # Get channel's configured quantity for this PT level
    qty_key = f'profit_target_qty_{hit_level_index}'
    trim_qty_pct = channel_info.get(qty_key, 25)  # Default 25%
    
    original_qty = instance.get('original_qty', instance.get('quantity'))
    remaining_qty = instance.get('remaining_qty', original_qty)
    
    # Calculate trim quantity
    trim_qty = int(original_qty * (trim_qty_pct / 100))
    trim_qty = min(trim_qty, remaining_qty)  # Can't trim more than remaining
    
    if trim_qty <= 0:
        return {'success': False, 'reason': 'No quantity to trim'}
    
    # Execute partial exit
    result = await self._execute_partial_exit(
        instance=instance,
        qty=trim_qty,
        reason=f'PT{hit_level_index} hit',
        price=signal_exit_price
    )
    
    # Update remaining quantity
    new_remaining = remaining_qty - trim_qty
    update_signal_instance(signal_instance_id, {
        'remaining_qty': new_remaining,
        f'pt{hit_level_index}_hit_at': datetime.now().isoformat(),
        f'pt{hit_level_index}_exit_qty': trim_qty
    })
    
    # Check if position fully closed
    if new_remaining <= 0:
        mark_exit_completed(signal_instance_id, 'profit_target')
    
    return {
        'success': True,
        'trimmed_qty': trim_qty,
        'remaining_qty': new_remaining,
        'broker_result': result
    }
```

### Conflict 4: Conditional Order Synchronization

**Problem**: Signal edit changes SL while conditional order is pending.

**Resolution - Sync conditional orders with signal updates**:

```python
# File: src/services/conditional_order_service.py - Add sync method

async def sync_with_signal_update(
    self,
    signal_instance_id: int,
    new_sl: float = None,
    new_pts: List[float] = None
) -> Dict:
    """
    Synchronize pending conditional orders with signal updates.
    
    Called when on_message_edit detects SL/PT changes.
    """
    # Find pending conditional orders for this signal
    pending_orders = get_pending_conditional_orders_by_signal(signal_instance_id)
    
    updated = []
    for order in pending_orders:
        if order['order_type'] == 'stop_loss' and new_sl:
            # Update the trigger price
            update_conditional_order(order['id'], {
                'trigger_price': new_sl,
                'updated_reason': 'Signal SL changed',
                'updated_at': datetime.now().isoformat()
            })
            updated.append(order['id'])
        
        elif order['order_type'] == 'profit_target' and new_pts:
            # Check if this PT is still valid
            if order['trigger_price'] not in new_pts:
                # PT was removed or hit - cancel the conditional
                cancel_conditional_order(order['id'], 'PT no longer in signal')
                updated.append(order['id'])
    
    return {'synced_orders': updated}
```

### Conflict 5: Concurrent SL Writer Locking

**Problem**: TrailingStopExecutor and on_message_edit both try to update current_sl.

**Resolution - Optimistic locking with version column**:

```python
# File: gui_app/database.py

signal_instance_locking_columns = [
    ('sl_version', 'INTEGER DEFAULT 0'),  # Increment on each SL change
]

def update_signal_instance_sl_atomic(
    instance_id: int,
    new_sl: float,
    expected_version: int,
    source: str
) -> bool:
    """
    Atomically update SL only if version matches.
    
    Returns True if update succeeded, False if version mismatch (retry needed).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE signal_instances 
        SET current_sl = ?, 
            sl_version = sl_version + 1,
            sl_update_source = ?,
            updated_at = ?
        WHERE id = ? AND sl_version = ?
    ''', (new_sl, source, datetime.now().isoformat(), instance_id, expected_version))
    
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    
    return rows_affected > 0  # True if update succeeded
```

```python
# Usage in SignalExitManager

async def handle_sl_update(self, signal_instance_id: int, new_sl: float, source: str) -> Dict:
    """Update SL with retry on version conflict."""
    max_retries = 3
    
    for attempt in range(max_retries):
        instance = get_signal_instance(signal_instance_id)
        current_version = instance.get('sl_version', 0)
        
        success = update_signal_instance_sl_atomic(
            instance_id=signal_instance_id,
            new_sl=new_sl,
            expected_version=current_version,
            source=source
        )
        
        if success:
            return {'success': True, 'new_sl': new_sl}
        
        # Version mismatch - another writer updated SL
        await asyncio.sleep(0.01)  # Brief delay before retry
    
    return {'success': False, 'reason': 'Version conflict after retries'}
```

### Industry-Grade Audit Logging

```python
# File: src/services/audit_logger.py (NEW FILE)

"""
Risk Event Audit Logger - Immutable audit trail for all risk decisions.
"""

from datetime import datetime
from enum import Enum


class RiskEventType(Enum):
    SL_UPDATE = 'sl_update'
    SL_REJECTED = 'sl_rejected'
    PT_HIT = 'pt_hit'
    EXIT_TRIGGERED = 'exit_triggered'
    EXIT_REJECTED = 'exit_rejected'
    TRAILING_ACTIVATED = 'trailing_activated'
    CIRCUIT_BREAKER_TRIGGERED = 'circuit_breaker_triggered'
    ORDER_FAILED = 'order_failed'
    ORDER_RETRY = 'order_retry'


def log_risk_event(
    event_type: RiskEventType,
    signal_instance_id: int,
    channel_id: str,
    source: str,
    details: Dict,
    before_state: Dict = None,
    after_state: Dict = None
):
    """Log an immutable risk event for audit trail."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO risk_events (
            event_type, signal_instance_id, channel_id, source,
            details, before_state, after_state, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        event_type.value,
        signal_instance_id,
        channel_id,
        source,
        json.dumps(details),
        json.dumps(before_state) if before_state else None,
        json.dumps(after_state) if after_state else None,
        datetime.now().isoformat()
    ))
    
    conn.commit()
    conn.close()
    
    # Also print for real-time monitoring
    print(f"[AUDIT] {event_type.value}: instance={signal_instance_id}, source={source}, {details}")
```

### Broker-Aware Order Modification

```python
# File: src/services/broker_integration.py

BROKER_CAPABILITIES = {
    'alpaca': {
        'supports_replace': True,
        'rate_limit_per_min': 200,
        'retry_on_failure': True,
    },
    'schwab': {
        'supports_replace': True,
        'rate_limit_per_min': 120,
        'retry_on_failure': True,
    },
    'ibkr': {
        'supports_replace': True,
        'rate_limit_per_min': 50,
        'retry_on_failure': True,
    },
    'robinhood': {
        'supports_replace': False,  # Must cancel + new
        'rate_limit_per_min': 60,
        'retry_on_failure': True,
    },
    'webull': {
        'supports_replace': False,  # Must cancel + new
        'rate_limit_per_min': 60,
        'retry_on_failure': True,
    },
    'tastytrade': {
        'supports_replace': False,  # Must cancel + new
        'rate_limit_per_min': 100,
        'retry_on_failure': True,
    },
}

async def modify_sl_order(
    broker: str,
    order_id: str,
    new_sl_price: float,
    symbol: str,
    quantity: int
) -> Dict:
    """
    Modify SL order using broker-appropriate method.
    
    - Alpaca/Schwab/IBKR: Use REPLACE order
    - Robinhood/Webull/Tastytrade: Cancel + New order
    """
    capabilities = BROKER_CAPABILITIES.get(broker, {})
    
    if capabilities.get('supports_replace'):
        return await _replace_sl_order(broker, order_id, new_sl_price)
    else:
        # Cancel existing, then place new
        cancel_result = await _cancel_order(broker, order_id)
        if not cancel_result['success']:
            return {'success': False, 'reason': 'Failed to cancel existing SL'}
        
        new_order_result = await _place_sl_order(broker, symbol, quantity, new_sl_price)
        return new_order_result
```

### Industry-Grade Checklist (Updated)

| Requirement | Status | Implementation |
|-------------|--------|----------------|
| Idempotency | ✅ Covered | exit_processed flag + last_processed_edit_id |
| Audit logging | ✅ Covered | risk_events table + log_risk_event() |
| Rollback safety | ✅ Covered | Optimistic locking + rollback on failure |
| Rate limiting | ✅ Covered | BROKER_CAPABILITIES rate_limit_per_min |
| Error recovery | ✅ Covered | Retry logic with max_retries |
| State consistency | ✅ Covered | sl_version for atomic updates |
| Testing strategy | ✅ Covered | Feature flags for paper trading first |
| Feature flags | ✅ Covered | enable_signal_exit_manager flag |
| Monitoring | ✅ Covered | Audit log + real-time prints |
| Documentation | ✅ Covered | This document |

---

## 🖥️ UI/UX ARCHITECTURE & CONFIGURATION

### Two-Tier Configuration Model

The system uses a **Global + Per-Channel Override** model:

```
┌──────────────────────────────────────────────────────────────┐
│                    GLOBAL DEFAULTS                            │
│              (/risk-management page)                          │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Signal Update Automation: OFF (default)                 │ │
│  │ Exit Strategy Mode: SIGNAL (default)                    │ │
│  │ Circuit Breaker: OFF (default)                          │ │
│  │ Trailing Stop Execution: OFF (default)                  │ │
│  │ Daily Loss Limit: $0 (disabled)                         │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│               PER-CHANNEL OVERRIDES                           │
│            (Channel detail modal)                             │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ □ Use Global Settings (checked = inherit)               │ │
│  │ ─────────────────────────────────────────────────────── │ │
│  │ Signal Update Automation: [Inherit/On/Off]              │ │
│  │ Exit Strategy Mode: [Inherit/Signal/Risk/Hybrid]        │ │
│  │ Channel-specific Daily Loss Limit: $___                 │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

### Global vs Per-Channel Matrix

| Setting | Global Location | Per-Channel Override | Default | Architect Recommendation |
|---------|-----------------|---------------------|---------|-------------------------|
| **Signal Update Automation** | /risk-management | ✅ Yes | **OFF** | OFF - Major behavior change |
| **Exit Strategy Mode** | /risk-management | ✅ Yes | **SIGNAL** | SIGNAL - Safest, follows trader |
| **Circuit Breaker** | /risk-management | ✅ Yes | **OFF** | OFF initially, prompt to enable |
| **Trailing Stop Execution** | /risk-management | ✅ Yes | **OFF** | OFF - Must opt-in |
| **Daily Loss Limit** | /risk-management | ✅ Yes | **$0 (disabled)** | Disabled, per-channel override |
| **Max Positions** | /risk-management | ✅ Yes | **10** | Sensible default |
| **Order Timeout** | /risk-management | ❌ Global only | **5 min** | Global is sufficient |

### Default Value Recommendations

| Feature | Default | Reason |
|---------|---------|--------|
| **on_message_edit handling** | **OFF** | Major behavior change - user must explicitly enable |
| **Exit Strategy Mode** | **SIGNAL** | Safest: follows trader signals exactly |
| **Circuit Breaker** | **OFF** | Show setup wizard prompt to enable |
| **Trailing Stop Execution** | **OFF** | Requires understanding - must opt-in |
| **Daily Loss Limit** | **$0 (disabled)** | User sets based on risk tolerance |

### UI Placement Recommendations

#### 1. Global Risk Management Page (`/risk-management`)

Add new card: **"Signal Update Automation"**

```html
<!-- File: gui_app/templates/risk_management.html -->

<div class="card bg-dark mb-4">
  <div class="card-header d-flex justify-content-between align-items-center">
    <h5 class="mb-0">
      <i class="fas fa-sync-alt me-2"></i>Signal Update Automation
      <span class="badge bg-warning ms-2">NEW</span>
    </h5>
    <div class="form-check form-switch">
      <input class="form-check-input" type="checkbox" id="enableSignalUpdateAutomation"
             {{ 'checked' if settings.enable_signal_update_automation else '' }}>
      <label class="form-check-label" for="enableSignalUpdateAutomation">Enable</label>
    </div>
  </div>
  <div class="card-body">
    <p class="text-muted mb-3">
      When enabled, the bot will automatically detect when traders <strong>edit their signals</strong> 
      (like C1apped updating stop loss or marking targets as hit) and update your broker orders accordingly.
    </p>
    
    <div class="alert alert-info">
      <i class="fas fa-info-circle me-2"></i>
      <strong>What this does:</strong>
      <ul class="mb-0 mt-2">
        <li>Detects when trader raises stop loss → Updates your broker stop loss</li>
        <li>Detects when profit targets are hit (strikethrough) → Triggers partial exits</li>
        <li>Detects "All out" exit signals → Closes your position</li>
      </ul>
    </div>
    
    <div class="alert alert-warning" id="signalAutomationWarning" style="display: none;">
      <i class="fas fa-exclamation-triangle me-2"></i>
      <strong>Warning:</strong> This will automatically modify your broker orders when signals are edited.
      Test with paper trading first!
    </div>
  </div>
</div>
```

#### 2. Exit Strategy Mode Selector

```html
<!-- Add to both /risk-management and channel detail modal -->

<div class="mb-4">
  <label class="form-label">
    <i class="fas fa-door-open me-2"></i>Exit Strategy Mode
  </label>
  
  <div class="btn-group w-100" role="group">
    <input type="radio" class="btn-check" name="exitStrategyMode" id="exitModeSignal" value="signal"
           {{ 'checked' if settings.exit_strategy_mode == 'signal' else '' }}>
    <label class="btn btn-outline-primary" for="exitModeSignal">
      <i class="fas fa-bullhorn me-1"></i> Signal
    </label>
    
    <input type="radio" class="btn-check" name="exitStrategyMode" id="exitModeRisk" value="risk"
           {{ 'checked' if settings.exit_strategy_mode == 'risk' else '' }}>
    <label class="btn btn-outline-warning" for="exitModeRisk">
      <i class="fas fa-shield-alt me-1"></i> Risk
    </label>
    
    <input type="radio" class="btn-check" name="exitStrategyMode" id="exitModeHybrid" value="hybrid"
           {{ 'checked' if settings.exit_strategy_mode == 'hybrid' else '' }}>
    <label class="btn btn-outline-success" for="exitModeHybrid">
      <i class="fas fa-balance-scale me-1"></i> Hybrid
    </label>
  </div>
  
  <div class="mt-2">
    <small class="text-muted" id="exitModeDescription">
      <!-- Updated dynamically based on selection -->
    </small>
  </div>
</div>

<script>
const exitModeDescriptions = {
  'signal': '📢 <strong>Signal Mode:</strong> Exits follow the trader exactly. Stop loss and profit targets come from signal only.',
  'risk': '🛡️ <strong>Risk Mode:</strong> Exits follow your channel settings. Trailing stop and channel profit targets override signal.',
  'hybrid': '⚖️ <strong>Hybrid Mode:</strong> Uses the TIGHTER protection. If trader sets SL at $1.19 but your trailing stop is at $1.22, uses $1.22.'
};

document.querySelectorAll('input[name="exitStrategyMode"]').forEach(radio => {
  radio.addEventListener('change', function() {
    document.getElementById('exitModeDescription').innerHTML = exitModeDescriptions[this.value];
  });
});
</script>
```

#### 3. Per-Channel Override in Channel Modal

```html
<!-- File: gui_app/templates/channel_modal.html (or similar) -->

<div class="accordion-item">
  <h2 class="accordion-header">
    <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" 
            data-bs-target="#advancedRiskSettings">
      <i class="fas fa-cog me-2"></i> Advanced Risk Settings
    </button>
  </h2>
  <div id="advancedRiskSettings" class="accordion-collapse collapse">
    <div class="accordion-body">
      
      <!-- Inherit from Global Toggle -->
      <div class="form-check mb-3">
        <input class="form-check-input" type="checkbox" id="useGlobalRiskSettings" checked>
        <label class="form-check-label" for="useGlobalRiskSettings">
          <strong>Use Global Risk Settings</strong>
          <small class="text-muted d-block">Uncheck to customize for this channel only</small>
        </label>
      </div>
      
      <div id="channelOverrideSettings" style="display: none;">
        <hr>
        
        <!-- Signal Update Automation Override -->
        <div class="mb-3">
          <label class="form-label">Signal Update Automation</label>
          <select class="form-select" name="signal_update_automation_override">
            <option value="inherit">Inherit from Global</option>
            <option value="on">Enabled for this channel</option>
            <option value="off">Disabled for this channel</option>
          </select>
        </div>
        
        <!-- Exit Strategy Mode Override -->
        <div class="mb-3">
          <label class="form-label">Exit Strategy Mode</label>
          <select class="form-select" name="exit_strategy_mode_override">
            <option value="inherit">Inherit from Global</option>
            <option value="signal">Signal (follow trader)</option>
            <option value="risk">Risk (follow channel settings)</option>
            <option value="hybrid">Hybrid (tightest protection)</option>
          </select>
        </div>
        
        <!-- Channel-specific Daily Loss Limit -->
        <div class="mb-3">
          <label class="form-label">Daily Loss Limit (this channel only)</label>
          <div class="input-group">
            <span class="input-group-text">$</span>
            <input type="number" class="form-control" name="channel_daily_loss_limit" 
                   placeholder="0 = use global">
          </div>
          <small class="text-muted">Set to 0 to use global limit</small>
        </div>
        
      </div>
    </div>
  </div>
</div>

<script>
document.getElementById('useGlobalRiskSettings').addEventListener('change', function() {
  document.getElementById('channelOverrideSettings').style.display = this.checked ? 'none' : 'block';
});
</script>
```

### User-Friendly Mode Explanations

| Mode | Icon | Simple Explanation | When to Use |
|------|------|-------------------|-------------|
| **Signal** | 📢 | "Follow the trader exactly" | Trust the trader's exits completely |
| **Risk** | 🛡️ | "Use your own risk settings" | You have your own exit strategy |
| **Hybrid** | ⚖️ | "Use whichever protects you more" | Best of both - never less protected |

### Confirmation Dialogs

```javascript
// When enabling Signal Update Automation
function enableSignalAutomation() {
  return confirm(
    "⚠️ Signal Update Automation\n\n" +
    "This will automatically update your broker orders when traders edit their signals.\n\n" +
    "What will happen:\n" +
    "• Stop loss changes → Your broker SL updated\n" +
    "• Target hit → Partial position sold\n" +
    "• Exit signal → Position closed\n\n" +
    "Recommendation: Test with paper trading first!\n\n" +
    "Enable Signal Update Automation?"
  );
}

// When switching to Hybrid mode
function switchToHybridMode() {
  return confirm(
    "⚖️ Hybrid Mode\n\n" +
    "In Hybrid mode:\n" +
    "• Uses the TIGHTER stop loss between signal and your settings\n" +
    "• Stop loss can only move UP (more protection), never down\n" +
    "• Trailing stop can override signal if it provides better protection\n\n" +
    "This provides maximum protection but may exit earlier than the trader.\n\n" +
    "Switch to Hybrid Mode?"
  );
}
```

### Database Schema for Settings

```python
# File: gui_app/database.py - Global settings table

global_risk_settings_columns = [
    ('enable_signal_update_automation', 'INTEGER DEFAULT 0'),  # OFF by default
    ('exit_strategy_mode', "TEXT DEFAULT 'signal'"),  # signal, risk, hybrid
    ('enable_circuit_breaker', 'INTEGER DEFAULT 0'),  # OFF by default
    ('enable_trailing_execution', 'INTEGER DEFAULT 0'),  # OFF by default
    ('global_daily_loss_limit', 'REAL DEFAULT 0'),  # 0 = disabled
    ('global_max_positions', 'INTEGER DEFAULT 10'),
    ('order_timeout_minutes', 'INTEGER DEFAULT 5'),
]

# Per-channel override columns (add to channels table)
channel_override_columns = [
    ('use_global_risk_settings', 'INTEGER DEFAULT 1'),  # 1 = inherit from global
    ('signal_update_automation_override', "TEXT DEFAULT 'inherit'"),  # inherit, on, off
    ('exit_strategy_mode_override', "TEXT DEFAULT 'inherit'"),  # inherit, signal, risk, hybrid
    ('channel_daily_loss_limit', 'REAL DEFAULT 0'),  # 0 = use global
]
```

### Feature Flag Rollout Strategy

| Phase | Users | Features Enabled | Duration |
|-------|-------|------------------|----------|
| **Phase 1** | Beta testers only | All features, paper trading only | 1 week |
| **Phase 2** | Opt-in users | All features, live trading allowed | 2 weeks |
| **Phase 3** | All new users | Defaults OFF, prompt to configure | Ongoing |
| **Phase 4** | Existing users | Grandfathered with all OFF, nag to enable | Ongoing |

### Grandfather Strategy for Existing Users

```python
# When user first accesses new risk management page after upgrade

def check_upgrade_needed(user_id: int) -> bool:
    """Check if user needs to acknowledge new features."""
    settings = get_global_risk_settings(user_id)
    return settings.get('acknowledged_v2_features') != True

def show_upgrade_banner():
    """Show banner explaining new features."""
    return """
    <div class="alert alert-info alert-dismissible">
      <h5>🎉 New Risk Management Features Available!</h5>
      <p>We've added powerful new automation features:</p>
      <ul>
        <li><strong>Signal Update Automation</strong> - Auto-update broker orders when traders edit signals</li>
        <li><strong>Exit Strategy Modes</strong> - Choose between Signal, Risk, or Hybrid exits</li>
        <li><strong>Circuit Breaker</strong> - Emergency kill switch for all trading</li>
      </ul>
      <p>All new features are <strong>disabled by default</strong>. Enable them when you're ready!</p>
      <button class="btn btn-primary" onclick="acknowledgeUpgrade()">Got it!</button>
    </div>
    """
```

---

## 1. WAXUI SIGNAL FORMAT - COMPLETE GAP ANALYSIS

### Current WaxUI Parsing (What Works)

| Pattern | Status | Example |
|---------|--------|---------|
| Entry | ✅ Works | `SPX here 12/05 6880C Avg. 4.00` |
| Trim | ⚠️ Partial | `Trim SPX here` (no profit % extracted) |
| Close | ✅ Works | `Closed SPX here` |

### WaxUI Gaps Identified (From Screenshot)

| Gap | Signal Format | Current Handling | Fix Required |
|-----|---------------|------------------|--------------|
| **Gap 1: Profit Ladder** | `4.00 - 5.50 ✓ 38%` | ❌ Not parsed | Extract entry, current, profit % |
| **Gap 2: Trim with %** | `Trim SPX here 4.00 - 4.80 ✓ 20%` | ❌ Only ticker | Extract trim %, new price |
| **Gap 3: More/Update** | `More SPX here 4.00 - 5.50 ✓ 38%` | ❌ Not detected | Add "More" pattern |
| **Gap 4: Hold States** | `Holding most.`, `Holding 1/2!`, `Holding runners only.` | ❌ Not parsed | Track position % remaining |
| **Gap 5: Trail Stops** | `Trail stops set @B/E` | ❌ Not detected | Set trailing stop to break-even |
| **Gap 6: Entry Linking** | Updates don't link to entry | ❌ No registry | WaxUI Entry Registry by ticker+expiry |
| **Gap 7: LOTTO Tag** | `@waxui LOTTO` | ⚠️ Partial | Flag as high-risk lotto play |

### WaxUI Patterns to Add

```python
# File: src/selfbot_webull.py (add after existing WAXUI patterns ~line 1369)

# Gap 1 & 2: Profit ladder with percentage
# Matches: "4.00 - 5.50 ✓ 38%" or "4.00 - 4.80 ✓ 20%"
WAXUI_PROFIT_LADDER_PATTERN = r'(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)\s*[✓✔️☑]?\s*(\d+)%'

# Gap 3: "More" update pattern
# Matches: "More SPX here" with profit ladder
WAXUI_MORE_PATTERN = r'[Mm]ore\s+([A-Za-z]+)\s+here'

# Gap 4: Holding states
WAXUI_HOLDING_PATTERNS = {
    'holding_most': r'[Hh]olding\s+most',
    'holding_majority': r'[Hh]olding\s+majority',
    'holding_half': r'[Hh]olding\s+1/2|[Hh]olding\s+half',
    'holding_runners': r'[Hh]olding\s+runners\s+only',
}

# Gap 5: Trail stops
# Matches: "Trail stops set @B/E" or "Trail stops @breakeven"
WAXUI_TRAIL_STOPS_PATTERN = r'[Tt]rail\s*stops?\s+(?:set\s+)?@\s*([Bb]/[Ee]|[Bb]reak\s*even|[0-9.]+)'

# Gap 7: LOTTO tag detection
WAXUI_LOTTO_PATTERN = r'LOTTO|[Ll]otto'
```

### WaxUI Entry Registry (New)

```python
# File: src/services/waxui_entry_registry.py (NEW FILE)

"""
WaxUI Entry Registry - Links updates to original entries.

Tracks active WaxUI positions to enable:
- Update signals to reference correct position
- Trim percentages to calculate quantities
- Trail stops to use correct entry price for B/E
"""

from typing import Dict, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field


@dataclass
class WaxUIEntry:
    ticker: str
    expiry: str
    strike: float
    opt_type: str
    entry_price: float
    quantity: int
    channel_id: str
    signal_instance_id: Optional[int] = None
    current_price: Optional[float] = None
    profit_pct: float = 0.0
    holding_state: str = 'full'  # full, most, majority, half, runners
    trailing_stop_enabled: bool = False
    trailing_stop_price: Optional[float] = None
    created_at: datetime = field(default_factory=datetime.now)


class WaxUIEntryRegistry:
    """Registry for active WaxUI positions."""
    
    def __init__(self):
        self._entries: Dict[str, WaxUIEntry] = {}  # key = ticker_expiry_strike
        self._ttl_hours = 48  # Auto-expire after 48 hours
    
    def _make_key(self, ticker: str, expiry: str = None, strike: float = None) -> str:
        """Create lookup key. Expiry/strike optional for fuzzy matching."""
        if expiry and strike:
            return f"{ticker}_{expiry}_{strike}"
        return ticker  # Fallback to ticker-only for updates
    
    def register_entry(self, entry: WaxUIEntry) -> str:
        """Register a new WaxUI entry."""
        key = self._make_key(entry.ticker, entry.expiry, entry.strike)
        self._entries[key] = entry
        self._cleanup_expired()
        return key
    
    def find_by_ticker(self, ticker: str) -> Optional[WaxUIEntry]:
        """Find most recent entry by ticker (for updates without expiry/strike)."""
        matches = [e for k, e in self._entries.items() if e.ticker.upper() == ticker.upper()]
        if matches:
            return max(matches, key=lambda e: e.created_at)
        return None
    
    def update_holding_state(self, ticker: str, state: str, current_price: float = None, profit_pct: float = None):
        """Update holding state from trim/more signals."""
        entry = self.find_by_ticker(ticker)
        if entry:
            entry.holding_state = state
            if current_price:
                entry.current_price = current_price
            if profit_pct:
                entry.profit_pct = profit_pct
    
    def set_trailing_stop(self, ticker: str, price: float = None, at_breakeven: bool = False):
        """Set trailing stop. If at_breakeven, use entry price."""
        entry = self.find_by_ticker(ticker)
        if entry:
            entry.trailing_stop_enabled = True
            if at_breakeven:
                entry.trailing_stop_price = entry.entry_price
            elif price:
                entry.trailing_stop_price = price
    
    def close_entry(self, ticker: str) -> Optional[WaxUIEntry]:
        """Mark entry as closed and return it."""
        entry = self.find_by_ticker(ticker)
        if entry:
            key = self._make_key(entry.ticker, entry.expiry, entry.strike)
            del self._entries[key]
            return entry
        return None
    
    def _cleanup_expired(self):
        """Remove entries older than TTL."""
        cutoff = datetime.now() - timedelta(hours=self._ttl_hours)
        expired = [k for k, e in self._entries.items() if e.created_at < cutoff]
        for k in expired:
            del self._entries[k]


# Global instance
waxui_registry = WaxUIEntryRegistry()
```

### WaxUI Parser Updates (File: src/selfbot_webull.py)

```python
# Add to WAXUI parsing section (~line 4067)

def parse_waxui_signal(text: str, channel_id: str) -> Optional[Dict]:
    """
    Complete WaxUI signal parser with update linking.
    
    Handles:
    - Entry: "SPX here 12/05 6880C Avg. 4.00"
    - Trim: "Trim SPX here 4.00 - 4.80 ✓ 20% Holding most."
    - More: "More SPX here 4.00 - 5.50 ✓ 38%"
    - Hold: "Holding runners only."
    - Trail: "Trail stops set @B/E"
    - Close: "Closed SPX here"
    """
    from src.services.waxui_entry_registry import waxui_registry, WaxUIEntry
    
    result = {
        'type': 'waxui',
        'action': None,
        'symbol': None,
        'entry_price': None,
        'current_price': None,
        'profit_pct': None,
        'holding_state': None,
        'trailing_stop': None,
    }
    
    # Check for LOTTO tag
    is_lotto = bool(re.search(WAXUI_LOTTO_PATTERN, text))
    result['is_lotto'] = is_lotto
    
    # 1. Check for ENTRY
    m = WAXUI_ENTRY_REGEX.search(text)
    if m:
        symbol, month, day, strike, opt_type, price = m.groups()
        result['action'] = 'BTO'
        result['symbol'] = symbol.upper()
        result['expiry'] = f"{month}/{day}"
        result['strike'] = float(strike)
        result['opt_type'] = opt_type.upper()
        result['entry_price'] = float(price.lstrip('.'))
        
        # Register in WaxUI registry
        entry = WaxUIEntry(
            ticker=result['symbol'],
            expiry=result['expiry'],
            strike=result['strike'],
            opt_type=result['opt_type'],
            entry_price=result['entry_price'],
            quantity=0,  # Will be calculated
            channel_id=channel_id
        )
        waxui_registry.register_entry(entry)
        return result
    
    # 2. Check for CLOSE
    m = WAXUI_CLOSE_REGEX.search(text)
    if m:
        symbol = m.group(1).upper()
        result['action'] = 'STC'
        result['symbol'] = symbol
        result['exit_type'] = 'close'
        
        # Get entry from registry for context
        entry = waxui_registry.close_entry(symbol)
        if entry:
            result['signal_instance_id'] = entry.signal_instance_id
        return result
    
    # 3. Check for TRIM
    m = WAXUI_TRIM_REGEX.search(text)
    if m:
        symbol = m.group(1).upper()
        result['action'] = 'TRIM'
        result['symbol'] = symbol
        
        # Extract profit ladder if present
        ladder = re.search(WAXUI_PROFIT_LADDER_PATTERN, text)
        if ladder:
            result['entry_price'] = float(ladder.group(1))
            result['current_price'] = float(ladder.group(2))
            result['profit_pct'] = float(ladder.group(3))
        
        # Check holding state
        for state, pattern in WAXUI_HOLDING_PATTERNS.items():
            if re.search(pattern, text):
                result['holding_state'] = state
                waxui_registry.update_holding_state(
                    symbol, state, 
                    result.get('current_price'),
                    result.get('profit_pct')
                )
                break
        
        return result
    
    # 4. Check for MORE (update)
    m = re.search(WAXUI_MORE_PATTERN, text)
    if m:
        symbol = m.group(1).upper()
        result['action'] = 'UPDATE'
        result['symbol'] = symbol
        
        # Extract profit ladder
        ladder = re.search(WAXUI_PROFIT_LADDER_PATTERN, text)
        if ladder:
            result['entry_price'] = float(ladder.group(1))
            result['current_price'] = float(ladder.group(2))
            result['profit_pct'] = float(ladder.group(3))
        
        # Check holding state
        for state, pattern in WAXUI_HOLDING_PATTERNS.items():
            if re.search(pattern, text):
                result['holding_state'] = state
                waxui_registry.update_holding_state(
                    symbol, state,
                    result.get('current_price'),
                    result.get('profit_pct')
                )
                break
        
        return result
    
    # 5. Check for TRAIL STOPS
    m = re.search(WAXUI_TRAIL_STOPS_PATTERN, text)
    if m:
        trail_value = m.group(1)
        
        # Find ticker in preceding text
        ticker_match = re.search(r'([A-Z]{1,5})', text)
        symbol = ticker_match.group(1) if ticker_match else None
        
        result['action'] = 'TRAIL_STOP'
        result['symbol'] = symbol
        
        if 'B/E' in trail_value.upper() or 'BREAK' in trail_value.upper():
            result['trailing_stop'] = 'breakeven'
            if symbol:
                waxui_registry.set_trailing_stop(symbol, at_breakeven=True)
        else:
            try:
                result['trailing_stop'] = float(trail_value)
                if symbol:
                    waxui_registry.set_trailing_stop(symbol, price=float(trail_value))
            except:
                pass
        
        return result
    
    # 6. Check for standalone holding state (no action word)
    for state, pattern in WAXUI_HOLDING_PATTERNS.items():
        if re.search(pattern, text):
            # Try to find ticker
            ticker_match = re.search(r'([A-Z]{2,5})', text)
            if ticker_match:
                symbol = ticker_match.group(1)
                result['action'] = 'HOLD_UPDATE'
                result['symbol'] = symbol
                result['holding_state'] = state
                
                # Extract profit ladder if present
                ladder = re.search(WAXUI_PROFIT_LADDER_PATTERN, text)
                if ladder:
                    result['entry_price'] = float(ladder.group(1))
                    result['current_price'] = float(ladder.group(2))
                    result['profit_pct'] = float(ladder.group(3))
                
                waxui_registry.update_holding_state(symbol, state)
                return result
    
    return None
```

---

## 2. C1APPED/TRADE IDEA - COMPLETE GAP ANALYSIS

### Current TRADE IDEA Handling (What Works)

| Feature | Status |
|---------|--------|
| Parse entry price | ✅ Works |
| Parse SL price | ✅ Works |
| Parse PT levels | ✅ Works |
| Strikethrough detection | ✅ Fixed recently |
| Store in signal_instances | ✅ Works |

### C1apped Gaps Identified

| Gap | Description | Impact | Priority |
|-----|-------------|--------|----------|
| **Gap 1: No Order ID Tracking** | Don't store broker order IDs | Can't modify SL orders | P0 |
| **Gap 2: No SL Modification** | SL changes in signal aren't sent to broker | Users miss updates | P0 |
| **Gap 3: No Debouncing** | Rapid SL updates can flood broker API | Rate limit errors | P0 |
| **Gap 4: No Exit Arbiter** | Signal and risk settings can conflict | Unexpected exits | P0 |
| **Gap 5: No Hybrid Mode** | Can't use both signal SL and trailing stop | Limited flexibility | P1 |
| **Gap 6: No Exit Signal Detection** | "All out", "Closed" not parsed | Manual close needed | P0 |

### C1apped Fixes Required

#### Fix 1: Add Order ID Columns (Database)

```python
# File: gui_app/database.py - Add to signal_instances table

# Already covered in Phase 1 schema:
# - sl_order_id TEXT
# - pt_order_ids TEXT (JSON array)
# - current_sl_price REAL
# - remaining_qty INTEGER
# - exit_strategy_mode TEXT
# - broker TEXT
```

#### Fix 2: SignalExitManager Integration

```python
# File: src/selfbot_webull.py - In TRADE IDEA handling (~line 8180)

# After parsing TRADE IDEA signal:
if is_trade_idea_signal(combined_content):
    trade_idea = parse_trade_idea(combined_content)
    if trade_idea:
        # Check if this is an UPDATE (existing position)
        existing_instance = get_open_signal_instance_by_fingerprint(fingerprint)
        
        if existing_instance:
            # This is an UPDATE - handle SL/PT changes
            old_sl = existing_instance.get('stop_loss')
            new_sl = trade_idea.get('stop_loss')
            
            if new_sl and old_sl and new_sl != old_sl:
                # Get exit strategy mode for this channel
                exit_strategy_mode = channel_info.get('exit_strategy_mode', 'signal')
                
                if exit_strategy_mode in ['signal', 'hybrid']:
                    # Route through ExitOrderArbiter
                    from src.services.exit_order_arbiter import exit_order_arbiter
                    from src.services.signal_exit_manager import signal_exit_manager
                    
                    arbiter_result = await exit_order_arbiter.request_sl_update(
                        signal_instance_id=existing_instance['id'],
                        source='signal',
                        new_sl_price=new_sl,
                        current_sl_price=old_sl,
                        exit_strategy_mode=exit_strategy_mode
                    )
                    
                    if arbiter_result['approved']:
                        sl_result = await signal_exit_manager.handle_sl_update(
                            signal_instance_id=existing_instance['id'],
                            new_sl_price=new_sl,
                            exit_strategy_mode=exit_strategy_mode
                        )
                        print(f"[TRADE IDEA] SL updated: ${old_sl} -> ${new_sl} ({sl_result.get('action')})")
        else:
            # This is a NEW ENTRY
            # ... existing entry logic ...
            
            # After placing order, register with SignalExitManager
            if get_feature_flag('enable_signal_exit_manager'):
                entry_result = await signal_exit_manager.handle_new_entry(
                    signal_instance_id=instance_id,
                    broker=broker_name,
                    ticker=ticker,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    profit_targets=profit_targets,
                    quantity=qty,
                    exit_strategy_mode=channel_info.get('exit_strategy_mode', 'signal')
                )
```

#### Fix 3: Exit Signal Detection

```python
# File: src/signals/parser.py - Add exit detection

TRADE_IDEA_EXIT_PATTERNS = [
    r'all\s*out',
    r'closed?\s+(?:this\s+)?(?:trade|position)',
    r'sold?\s+(?:all|everything)',
    r'exited?\s+(?:this\s+)?(?:trade|position)',
    r'stopped?\s+out',
    r'took\s+(?:the\s+)?loss',
]

def is_trade_idea_exit(text: str) -> bool:
    """Check if text indicates an exit signal."""
    for pattern in TRADE_IDEA_EXIT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False

def parse_trade_idea_exit(text: str) -> Optional[Dict]:
    """Parse exit signal to extract ticker and exit type."""
    # Extract ticker
    ticker_match = re.search(r'\$?([A-Z]{1,5})\b', text)
    if not ticker_match:
        return None
    
    ticker = ticker_match.group(1)
    
    # Determine exit type
    if re.search(r'stopped?\s*out|took.*loss', text, re.IGNORECASE):
        exit_type = 'stop_loss'
    elif re.search(r'target|profit', text, re.IGNORECASE):
        exit_type = 'profit_target'
    else:
        exit_type = 'manual'
    
    return {
        'ticker': ticker,
        'exit_type': exit_type,
        'action': 'STC',
        'is_exit': True
    }
```

---

## 3. RISK MANAGEMENT SETTINGS - COMPLETE GAP ANALYSIS

### Current Risk Settings (What Exists)

| Setting | Table | Column | Status |
|---------|-------|--------|--------|
| Stop Loss % | channels | stop_loss_pct | ✅ Stored |
| Trailing Stop % | channels | trailing_stop_pct | ✅ Stored |
| Trailing Activation % | channels | trailing_activation_pct | ✅ Stored |
| Profit Target 1-4 | channels | profit_target_*_pct | ✅ Stored |
| PT Trim Quantities | channels | profit_target_qty_* | ✅ Stored |
| Exit Strategy Mode | channels | exit_strategy_mode | ✅ Stored |
| Global Risk Settings | risk_management_settings | * | ✅ Stored |

### Risk Management Gaps Identified

| Gap | Description | Impact | Priority |
|-----|-------------|--------|----------|
| **Gap 1: Stop Loss Type** | Only % supported, not fixed or from_signal | Limited flexibility | P1 |
| **Gap 2: Trailing Not Enforced** | Settings stored but not executed | Feature doesn't work | P0 |
| **Gap 3: No Daily Loss Limit** | No per-channel or global limit | Unlimited losses | P0 |
| **Gap 4: No Circuit Breaker** | No kill switch | Can't stop in emergency | P0 |
| **Gap 5: No Order Timeout** | Orders can hang indefinitely | Stuck orders | P1 |
| **Gap 6: No Position Limits** | Can open unlimited positions | Over-exposure | P1 |
| **Gap 7: Broker Capability Unknown** | UI shows all options regardless of broker | User confusion | P2 |
| **Gap 8: Exit Mode Not Enforced** | Stored but not respected during execution | Unexpected behavior | P0 |
| **Gap 9: No Risk Event Logging** | No audit trail for risk decisions | No debugging | P1 |

### Risk Management Fixes Required

#### Fix 1: Add Missing Columns

```python
# File: gui_app/database.py - Add to channels table

channel_new_columns = [
    ('stop_loss_type', "TEXT DEFAULT 'percentage'"),  # percentage, fixed, from_signal
    ('stop_loss_fixed', 'REAL DEFAULT NULL'),
    ('max_daily_loss', 'REAL DEFAULT NULL'),
    ('max_positions', 'INTEGER DEFAULT 10'),
    ('order_timeout_minutes', 'INTEGER DEFAULT 5'),
    ('circuit_breaker_enabled', 'INTEGER DEFAULT 1'),
]
```

#### Fix 2: Trailing Stop Execution

```python
# File: src/services/trailing_stop_executor.py (NEW FILE)

"""
Trailing Stop Executor - Actually enforces trailing stop settings.

Current problem: trailing_stop_pct and trailing_activation_pct are stored
but never checked during position lifecycle.

Solution: Monitor positions and update broker SL when trailing conditions met.
"""

import asyncio
from typing import Dict, Optional
from datetime import datetime

class TrailingStopExecutor:
    """
    Executes trailing stop logic for open positions.
    
    Workflow:
    1. Position opens at entry_price
    2. Monitor current_price vs entry_price
    3. When profit >= trailing_activation_pct, activate trailing
    4. Calculate trailing_stop_price = current_price * (1 - trailing_stop_pct/100)
    5. If trailing_stop_price > current_sl, update SL via SignalExitManager
    """
    
    def __init__(self, signal_exit_manager, exit_order_arbiter):
        self.sem = signal_exit_manager
        self.arbiter = exit_order_arbiter
        self._active_trails = {}  # signal_instance_id -> trail state
    
    async def check_and_update(
        self,
        signal_instance_id: int,
        entry_price: float,
        current_price: float,
        current_sl_price: float,
        trailing_activation_pct: float,
        trailing_stop_pct: float,
        exit_strategy_mode: str
    ) -> Optional[Dict]:
        """
        Check if trailing stop should be updated.
        
        Returns update result if SL was modified, None otherwise.
        """
        # Calculate profit percentage
        profit_pct = ((current_price - entry_price) / entry_price) * 100
        
        # Check if trailing is activated
        is_activated = signal_instance_id in self._active_trails
        should_activate = profit_pct >= trailing_activation_pct
        
        if not is_activated and should_activate:
            # Activate trailing
            self._active_trails[signal_instance_id] = {
                'activated_at': datetime.now(),
                'activation_price': current_price,
                'highest_price': current_price
            }
            print(f"[TRAILING] Activated for {signal_instance_id} at {profit_pct:.1f}% profit")
        
        if not is_activated and not should_activate:
            # Not yet at activation threshold
            return None
        
        # Update highest price
        trail_state = self._active_trails.get(signal_instance_id, {})
        highest = max(trail_state.get('highest_price', current_price), current_price)
        trail_state['highest_price'] = highest
        self._active_trails[signal_instance_id] = trail_state
        
        # Calculate new trailing stop
        new_trailing_sl = highest * (1 - trailing_stop_pct / 100)
        
        # Only update if new SL is higher (tighter for long)
        if new_trailing_sl > current_sl_price:
            # Request update through arbiter
            arbiter_result = await self.arbiter.request_sl_update(
                signal_instance_id=signal_instance_id,
                source='trailing',
                new_sl_price=new_trailing_sl,
                current_sl_price=current_sl_price,
                exit_strategy_mode=exit_strategy_mode
            )
            
            if arbiter_result['approved']:
                # Execute the update
                result = await self.sem.handle_sl_update(
                    signal_instance_id=signal_instance_id,
                    new_sl_price=new_trailing_sl,
                    exit_strategy_mode=exit_strategy_mode,
                    source='trailing'
                )
                print(f"[TRAILING] SL raised: ${current_sl_price:.2f} -> ${new_trailing_sl:.2f}")
                return result
        
        return None
    
    def deactivate(self, signal_instance_id: int):
        """Remove trailing tracking for a closed position."""
        if signal_instance_id in self._active_trails:
            del self._active_trails[signal_instance_id]


# Global instance (initialize after SignalExitManager)
trailing_executor = None
```

#### Fix 3: Circuit Breaker & Daily Loss Limit

See Phase 4 in INDUSTRY_GRADE_RISK_MANAGEMENT_PLAN.md for complete CircuitBreaker implementation.

---

## 4. CONDITIONAL ORDERS - COMPLETE GAP ANALYSIS

### Current Conditional Order System (What Works)

| Feature | Status |
|---------|--------|
| Create conditional order | ✅ Works |
| Price monitoring (Finnhub/Broker) | ✅ Works |
| Trigger on price condition | ✅ Works |
| Execute order on trigger | ✅ Works |
| Three-tier fallback | ✅ Works |

### Conditional Order Gaps Identified

| Gap | Description | Impact | Priority |
|-----|-------------|--------|----------|
| **Gap 1: No Risk Gate** | Bypasses circuit breaker | Trades during halt | P0 |
| **Gap 2: No Daily Limit Check** | Bypasses daily loss limit | Over-loss | P0 |
| **Gap 3: No Order Timeout/Expiry** | Stale triggers never expire | Outdated executions | P1 |
| **Gap 4: No Hybrid Exit** | Doesn't coordinate with ExitArbiter | Conflicting exits | P1 |
| **Gap 5: No Order State Tracking** | No broker order ID storage | Can't modify orders | P1 |

### Conditional Order Fixes Required

```python
# File: src/services/conditional_order_service.py - Add to execute_order method

async def execute_order(self, order: ConditionalOrder) -> bool:
    """Execute a triggered conditional order with risk checks."""
    
    # NEW: Check circuit breaker first
    from src.services.circuit_breaker import circuit_breaker
    if circuit_breaker.is_halted:
        print(f"[CONDITIONAL] ❌ Order blocked: Trading halted")
        await self._update_status(order.id, OrderStatus.CANCELED, 'circuit_breaker_halt')
        return False
    
    # NEW: Check daily loss limit
    trade_check = await circuit_breaker.check_trade_allowed(
        channel_id=order.channel_id,
        trade_value=order.quantity * order.limit_price if order.limit_price else 0
    )
    
    if not trade_check['allowed']:
        print(f"[CONDITIONAL] ❌ Order blocked: {trade_check['reason']}")
        await self._update_status(order.id, OrderStatus.CANCELED, trade_check['reason'])
        return False
    
    # NEW: Route through SignalExitManager if enabled
    if get_feature_flag('enable_signal_exit_manager'):
        from src.services.signal_exit_manager import signal_exit_manager
        
        result = await signal_exit_manager.handle_new_entry(
            signal_instance_id=None,  # Will be created
            broker=order.broker,
            ticker=order.symbol,
            entry_price=order.limit_price or order.trigger_price,
            stop_loss=order.stop_loss,
            profit_targets=[order.profit_target] if order.profit_target else [],
            quantity=order.quantity,
            exit_strategy_mode=order.exit_strategy_mode or 'signal'
        )
        
        if result['success']:
            order.broker_order_id = result['entry_order_id']
            await self._update_status(order.id, OrderStatus.TRACKING)
            return True
    
    # Fallback to direct broker execution
    # ... existing code ...
```

---

## 5. TRAILING STOP ACTIVATION - COMPLETE GAP ANALYSIS

### Current Trailing Stop State

| Component | Status |
|-----------|--------|
| trailing_stop_pct column | ✅ Exists in channels |
| trailing_activation_pct column | ✅ Exists in channels |
| UI to set values | ✅ Works |
| API to save values | ✅ Works |
| Actual execution | ❌ NOT IMPLEMENTED |

### Trailing Stop Gaps

| Gap | Description | Fix Required |
|-----|-------------|--------------|
| **Gap 1: No Price Monitoring** | Don't track current price vs entry | Add price feed integration |
| **Gap 2: No Activation Check** | Never check if activation % reached | Add check in monitoring loop |
| **Gap 3: No SL Update Logic** | Never calculate trailing SL | Add TrailingStopExecutor |
| **Gap 4: No Broker SL Modification** | Never send SL update to broker | Route through SignalExitManager |

### Complete Trailing Stop Implementation

```python
# File: src/services/position_monitor.py (NEW FILE)

"""
Position Monitor - Tracks open positions for trailing stops and risk management.

Runs as background task, polling positions every 5 seconds.
"""

import asyncio
from typing import Dict, List
from datetime import datetime


class PositionMonitor:
    """
    Monitors open positions for:
    1. Trailing stop activation and updates
    2. Profit target hits
    3. Stop loss proximity warnings
    """
    
    def __init__(self, db_path: str = 'bot_data.db'):
        self.db_path = db_path
        self._running = False
        self._interval_seconds = 5
    
    async def start(self):
        """Start position monitoring loop."""
        self._running = True
        print("[POSITION MONITOR] Started")
        
        while self._running:
            try:
                await self._check_all_positions()
            except Exception as e:
                print(f"[POSITION MONITOR] Error: {e}")
            
            await asyncio.sleep(self._interval_seconds)
    
    async def stop(self):
        """Stop monitoring."""
        self._running = False
        print("[POSITION MONITOR] Stopped")
    
    async def _check_all_positions(self):
        """Check all open positions for trailing stop updates."""
        from gui_app.database import get_open_signal_instances
        from src.services.trailing_stop_executor import trailing_executor
        from src.services.price_service import get_current_price
        
        positions = get_open_signal_instances()
        
        for pos in positions:
            # Skip if no trailing stop configured
            if not pos.get('trailing_stop_pct') or pos.get('trailing_stop_pct') <= 0:
                continue
            
            # Get current price
            ticker = pos.get('ticker')
            current_price = await get_current_price(ticker)
            
            if not current_price:
                continue
            
            # Get channel settings
            channel_id = pos.get('channel_id')
            channel_info = get_channel_info(channel_id)
            
            trailing_activation_pct = pos.get('trailing_activation_pct') or channel_info.get('trailing_activation_pct') or 5.0
            trailing_stop_pct = pos.get('trailing_stop_pct') or channel_info.get('trailing_stop_pct') or 3.0
            exit_strategy_mode = pos.get('exit_strategy_mode') or channel_info.get('exit_strategy_mode') or 'risk'
            
            # Only apply trailing in risk or hybrid mode
            if exit_strategy_mode not in ['risk', 'hybrid']:
                continue
            
            # Check and update trailing stop
            await trailing_executor.check_and_update(
                signal_instance_id=pos['id'],
                entry_price=pos['entry_price'],
                current_price=current_price,
                current_sl_price=pos.get('current_sl_price') or pos.get('stop_loss'),
                trailing_activation_pct=trailing_activation_pct,
                trailing_stop_pct=trailing_stop_pct,
                exit_strategy_mode=exit_strategy_mode
            )


# Global instance
position_monitor = PositionMonitor()
```

---

## FILE REFERENCE MATRIX

### New Files to Create

| File | Description | Priority |
|------|-------------|----------|
| `src/services/waxui_entry_registry.py` | WaxUI position tracking | P0 |
| `src/services/signal_exit_manager.py` | Order lifecycle manager | P0 |
| `src/services/exit_order_arbiter.py` | Exit precedence rules | P0 |
| `src/services/circuit_breaker.py` | Kill switch & limits | P0 |
| `src/services/trailing_stop_executor.py` | Trailing stop logic | P0 |
| `src/services/position_monitor.py` | Position monitoring loop | P0 |
| `src/services/broker_integration.py` | Broker registry | P1 |
| `src/services/event_bus.py` | Event pub/sub | P2 |

### Files to Modify

| File | Changes | Priority |
|------|---------|----------|
| `src/selfbot_webull.py` | Add WaxUI patterns, SignalExitManager integration | P0 |
| `src/signals/parser.py` | Add exit signal detection | P0 |
| `src/services/conditional_order_service.py` | Add risk gate checks | P1 |
| `gui_app/database.py` | Add new columns and tables | P0 |
| `gui_app/routes.py` | Add risk management endpoints | P1 |

---

## IMPLEMENTATION ORDER

### Phase 1: Database Schema (Day 1)
1. Add columns to channels table
2. Add columns to signal_instances table
3. Create order_states table
4. Create risk_events table
5. Create broker_capabilities table
6. Create global_risk_settings table
7. Create feature_flags table

### Phase 2: Core Services (Days 2-3)
1. Implement CircuitBreaker (safety first)
2. Implement SignalExitManager
3. Implement ExitOrderArbiter
4. Implement TrailingStopExecutor
5. Implement PositionMonitor

### Phase 3: WaxUI Enhancement (Day 4)
1. Add new WaxUI patterns
2. Create WaxUIEntryRegistry
3. Implement parse_waxui_signal
4. Wire into selfbot_webull.py

### Phase 4: C1apped/TRADE IDEA Integration (Day 5)
1. Add exit signal detection
2. Integrate SignalExitManager into TRADE IDEA flow
3. Implement SL update propagation
4. Add debouncing

### Phase 5: Conditional Orders V2 (Day 6)
1. Add risk gate checks
2. Add timeout/expiry
3. Integrate with SignalExitManager
4. Add order state tracking

### Phase 6: Testing & Rollout (Days 7-8)
1. Paper trading validation
2. Enable feature flags one by one
3. Monitor logs for issues
4. Gradual live rollout

---

## FEATURE FLAGS FOR SAFE ROLLOUT

```python
# Enable one at a time, test thoroughly before next

FEATURE_FLAGS = {
    'enable_circuit_breaker': True,      # Safe, just adds checks
    'enable_signal_exit_manager': False, # Medium risk
    'enable_exit_arbiter': False,        # Medium risk
    'enable_waxui_v2': False,            # Low risk
    'enable_trailing_executor': False,   # Medium risk
    'enable_conditional_v2': False,      # Medium risk
}
```

---

*Generated: January 12, 2026*
*Scope: Complete Gap Analysis for WaxUI, C1apped, Risk Management, Conditional Orders*
