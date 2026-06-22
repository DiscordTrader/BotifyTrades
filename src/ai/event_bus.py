"""Fire-and-forget event bus for AI modules. Never blocks the caller."""
import threading
from typing import Dict, Any, List, Callable

_handlers: Dict[str, List[Callable]] = {}
_lock = threading.Lock()

def on(event: str, handler: Callable):
    """Register a handler for an event. Thread-safe."""
    with _lock:
        if event not in _handlers:
            _handlers[event] = []
        _handlers[event].append(handler)

def emit(event: str, data: Any = None):
    """Emit event to all handlers. Fire-and-forget in background thread."""
    with _lock:
        handlers = list(_handlers.get(event, []))
    if not handlers:
        return
    # Run handlers in background thread — never block caller
    def _run():
        for handler in handlers:
            try:
                handler(data)
            except Exception as e:
                print(f'[AI_EVENT] Handler error on {event}: {e}')
    threading.Thread(target=_run, daemon=True, name=f'ai_event_{event}').start()

# Standard events
EVENT_TRADE_CLOSE = 'trade_close'
EVENT_SIGNAL_ARRIVE = 'signal_arrive'
EVENT_FILL_DETECTED = 'fill_detected'
EVENT_POSITION_UPDATE = 'position_update'

def emit_trade_close(trade_data: dict):
    emit(EVENT_TRADE_CLOSE, trade_data)

def emit_signal_arrive(signal: dict):
    emit(EVENT_SIGNAL_ARRIVE, signal)

def emit_fill_detected(fill_data: dict):
    emit(EVENT_FILL_DETECTED, fill_data)
