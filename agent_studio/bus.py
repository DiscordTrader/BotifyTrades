"""
Message bus for inter-agent communication.
Persists all messages to SQLite and pushes to SSE client queues in real-time.
"""
import json
import queue
import threading
from typing import List, Callable, Dict, Optional
from .agent_types import AgentMessage, AgentState
from .db_adapter import AgentDBAdapter
from .config import AgentConfig


class MessageBus:
    def __init__(self, db: AgentDBAdapter):
        self._db = db
        self._subscribers: Dict[str, List[Callable]] = {}
        self._sse_queues: List[queue.Queue] = []
        self._lock = threading.Lock()

    def publish(self, message: AgentMessage):
        message.content = AgentConfig.scrub_secrets(message.content)
        message.sequence_number = self._db.get_next_sequence(message.task_id)
        self._db.save_message(message)

        with self._lock:
            callbacks = list(self._subscribers.get(message.to_agent, []))
            callbacks += list(self._subscribers.get("broadcast", []))
        for cb in callbacks:
            try:
                cb(message)
            except Exception:
                pass

        event_data = self._format_sse_event(message)
        with self._lock:
            dead_queues = []
            for q in self._sse_queues:
                try:
                    q.put_nowait(event_data)
                except queue.Full:
                    dead_queues.append(q)
            for q in dead_queues:
                self._sse_queues.remove(q)

    def publish_state(self, state: AgentState):
        self._db.save_agent_state(state)
        event_data = f"event: agent_state\ndata: {json.dumps(state.to_dict())}\n\n"
        with self._lock:
            dead_queues = []
            for q in self._sse_queues:
                try:
                    q.put_nowait(event_data)
                except queue.Full:
                    dead_queues.append(q)
            for q in dead_queues:
                self._sse_queues.remove(q)

    def subscribe(self, agent_name: str, callback: Callable):
        with self._lock:
            if agent_name not in self._subscribers:
                self._subscribers[agent_name] = []
            self._subscribers[agent_name].append(callback)

    def unsubscribe(self, agent_name: str, callback: Callable):
        with self._lock:
            if agent_name in self._subscribers:
                self._subscribers[agent_name] = [
                    cb for cb in self._subscribers[agent_name] if cb is not callback
                ]

    def subscribe_sse(self) -> Optional[queue.Queue]:
        with self._lock:
            if len(self._sse_queues) >= AgentConfig.MAX_SSE_CLIENTS:
                return None
            q = queue.Queue(maxsize=200)
            self._sse_queues.append(q)
            return q

    def unsubscribe_sse(self, q: queue.Queue):
        with self._lock:
            if q in self._sse_queues:
                self._sse_queues.remove(q)

    def get_messages(self, task_id: str, since_sequence: int = 0) -> List[AgentMessage]:
        return self._db.get_messages(task_id, since_sequence)

    def _format_sse_event(self, message: AgentMessage) -> str:
        event_type = message.message_type
        data = json.dumps(message.to_dict(), default=str)
        return f"event: {event_type}\ndata: {data}\n\n"
