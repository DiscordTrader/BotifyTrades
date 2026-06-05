"""
SQLite adapter for the agent system.
Uses a dedicated agent_data.db — fully isolated from the trading bot's bot_data.db.
"""
import sqlite3
import json
import threading
from typing import List, Optional, Dict, Any
from .agent_types import AgentMessage, AgentState, TaskState
from .config import AgentConfig


class AgentDBAdapter:
    def __init__(self, db_path: str = None):
        self._db_path = db_path or AgentConfig.get_db_path()
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            conn = sqlite3.connect(self._db_path, timeout=30)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS agent_tasks (
                id TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                priority TEXT DEFAULT 'normal',
                current_phase TEXT DEFAULT '',
                approval_mode TEXT DEFAULT 'review',
                model_override TEXT,
                created_at TEXT,
                started_at TEXT,
                completed_at TEXT,
                result_summary TEXT,
                error_message TEXT,
                git_branch TEXT,
                git_commit_sha TEXT,
                version TEXT,
                cost_estimate TEXT,
                actual_cost TEXT,
                metadata TEXT
            );

            CREATE TABLE IF NOT EXISTS agent_messages (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                from_agent TEXT NOT NULL,
                to_agent TEXT NOT NULL,
                message_type TEXT NOT NULL,
                content TEXT,
                metadata TEXT,
                sequence_number INTEGER,
                created_at TEXT,
                FOREIGN KEY (task_id) REFERENCES agent_tasks(id)
            );

            CREATE TABLE IF NOT EXISTS agent_states (
                agent_name TEXT PRIMARY KEY,
                status TEXT DEFAULT 'idle',
                current_task_id TEXT,
                progress_pct INTEGER DEFAULT 0,
                last_message_id TEXT,
                started_at TEXT,
                token_usage TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS agent_auth (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS agent_feedback (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                message_id TEXT,
                rating TEXT NOT NULL,
                comment TEXT,
                created_at TEXT,
                FOREIGN KEY (task_id) REFERENCES agent_tasks(id)
            );

            CREATE INDEX IF NOT EXISTS idx_messages_task ON agent_messages(task_id);
            CREATE INDEX IF NOT EXISTS idx_messages_type ON agent_messages(message_type);
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON agent_tasks(status);
            CREATE INDEX IF NOT EXISTS idx_feedback_task ON agent_feedback(task_id);
        """)
        conn.commit()

    def save_task(self, task: TaskState):
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO agent_tasks
            (id, description, status, priority, current_phase, approval_mode,
             model_override, created_at, started_at, completed_at, result_summary,
             error_message, git_branch, git_commit_sha, version, cost_estimate,
             actual_cost, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task.id, task.description, task.status, task.priority,
            task.current_phase, task.approval_mode, task.model_override,
            task.created_at, task.started_at, task.completed_at,
            task.result_summary, task.error_message, task.git_branch,
            task.git_commit_sha, task.version,
            json.dumps(task.cost_estimate) if task.cost_estimate else None,
            json.dumps(task.actual_cost) if task.actual_cost else None,
            None,
        ))
        conn.commit()

    def get_task(self, task_id: str) -> Optional[TaskState]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM agent_tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None
        return self._row_to_task(row)

    def list_tasks(self, status: str = None, limit: int = 20, offset: int = 0) -> List[TaskState]:
        conn = self._get_conn()
        if status:
            rows = conn.execute(
                "SELECT * FROM agent_tasks WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agent_tasks ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset)
            ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def update_task_status(self, task_id: str, status: str, **kwargs):
        conn = self._get_conn()
        sets = ["status = ?"]
        vals = [status]
        for key, val in kwargs.items():
            if key in ("current_phase", "started_at", "completed_at", "error_message",
                       "git_branch", "git_commit_sha", "version", "result_summary"):
                sets.append(f"{key} = ?")
                vals.append(val)
            elif key == "actual_cost":
                sets.append("actual_cost = ?")
                vals.append(json.dumps(val) if val else None)
        vals.append(task_id)
        conn.execute(f"UPDATE agent_tasks SET {', '.join(sets)} WHERE id = ?", vals)
        conn.commit()

    def save_message(self, msg: AgentMessage):
        conn = self._get_conn()
        content = AgentConfig.scrub_secrets(msg.content)
        metadata_str = json.dumps(msg.metadata) if msg.metadata else None
        if metadata_str:
            metadata_str = AgentConfig.scrub_secrets(metadata_str)
        conn.execute("""
            INSERT OR REPLACE INTO agent_messages
            (id, task_id, from_agent, to_agent, message_type, content, metadata,
             sequence_number, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            msg.id, msg.task_id, msg.from_agent, msg.to_agent,
            msg.message_type, content, metadata_str,
            msg.sequence_number, msg.timestamp,
        ))
        conn.commit()

    def get_messages(self, task_id: str, since_sequence: int = 0) -> List[AgentMessage]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM agent_messages WHERE task_id = ? AND sequence_number > ? ORDER BY sequence_number",
            (task_id, since_sequence)
        ).fetchall()
        return [self._row_to_message(r) for r in rows]

    def get_next_sequence(self, task_id: str) -> int:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT MAX(sequence_number) FROM agent_messages WHERE task_id = ?",
            (task_id,)
        ).fetchone()
        current = row[0] if row[0] is not None else 0
        return current + 1

    def save_agent_state(self, state: AgentState):
        conn = self._get_conn()
        from datetime import datetime, timezone
        conn.execute("""
            INSERT OR REPLACE INTO agent_states
            (agent_name, status, current_task_id, progress_pct, last_message_id,
             started_at, token_usage, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            state.name, state.status, state.current_task_id, state.progress_pct,
            state.last_message_id, state.started_at,
            json.dumps(state.token_usage),
            datetime.now(timezone.utc).isoformat(),
        ))
        conn.commit()

    def get_agent_states(self) -> Dict[str, AgentState]:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM agent_states").fetchall()
        result = {}
        for r in rows:
            result[r["agent_name"]] = AgentState(
                name=r["agent_name"],
                status=r["status"] or "idle",
                current_task_id=r["current_task_id"],
                progress_pct=r["progress_pct"] or 0,
                last_message_id=r["last_message_id"],
                started_at=r["started_at"],
                token_usage=json.loads(r["token_usage"]) if r["token_usage"] else {"input": 0, "output": 0},
            )
        return result

    def recover_stale_tasks(self, stale_minutes: int = 10) -> List[str]:
        conn = self._get_conn()
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)).isoformat()
        rows = conn.execute(
            "SELECT id FROM agent_tasks WHERE status = 'in_progress' AND started_at < ?",
            (cutoff,)
        ).fetchall()
        recovered = []
        for row in rows:
            task_id = row["id"]
            conn.execute(
                "UPDATE agent_tasks SET status = 'failed', error_message = 'Recovered: task was stale after restart' WHERE id = ?",
                (task_id,)
            )
            recovered.append(task_id)
        if recovered:
            conn.commit()
        return recovered

    def get_auth_settings(self) -> dict:
        conn = self._get_conn()
        rows = conn.execute("SELECT key, value FROM agent_auth").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def save_auth_settings(self, settings: dict):
        conn = self._get_conn()
        for key, value in settings.items():
            conn.execute(
                "INSERT OR REPLACE INTO agent_auth (key, value) VALUES (?, ?)",
                (key, str(value) if value is not None else ""),
            )
        conn.commit()

    def save_feedback(self, task_id: str, rating: str, message_id: str = None, comment: str = ""):
        import uuid
        from datetime import datetime, timezone
        conn = self._get_conn()
        conn.execute("""
            INSERT INTO agent_feedback (id, task_id, message_id, rating, comment, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            str(uuid.uuid4()), task_id, message_id, rating, comment,
            datetime.now(timezone.utc).isoformat(),
        ))
        conn.commit()

    def get_feedback(self, task_id: str) -> list:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM agent_feedback WHERE task_id = ? ORDER BY created_at",
            (task_id,)
        ).fetchall()
        return [{"id": r["id"], "task_id": r["task_id"], "message_id": r["message_id"],
                 "rating": r["rating"], "comment": r["comment"], "created_at": r["created_at"]}
                for r in rows]

    def _row_to_task(self, row) -> TaskState:
        return TaskState(
            id=row["id"],
            description=row["description"],
            status=row["status"],
            priority=row["priority"] or "normal",
            current_phase=row["current_phase"] or "",
            approval_mode=row["approval_mode"] or "review",
            model_override=row["model_override"],
            created_at=row["created_at"] or "",
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            git_branch=row["git_branch"],
            git_commit_sha=row["git_commit_sha"],
            version=row["version"],
            error_message=row["error_message"],
            cost_estimate=json.loads(row["cost_estimate"]) if row["cost_estimate"] else None,
            actual_cost=json.loads(row["actual_cost"]) if row["actual_cost"] else None,
            result_summary=row["result_summary"],
        )

    def _row_to_message(self, row) -> AgentMessage:
        return AgentMessage(
            id=row["id"],
            task_id=row["task_id"],
            from_agent=row["from_agent"],
            to_agent=row["to_agent"],
            message_type=row["message_type"],
            content=row["content"] or "",
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            sequence_number=row["sequence_number"] or 0,
            timestamp=row["created_at"] or "",
        )
