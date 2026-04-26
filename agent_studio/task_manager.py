"""
Task state machine — manages task lifecycle from pending to complete/failed.
Handles crash recovery on startup.
"""
from datetime import datetime, timezone
from typing import Optional, List
from .agent_types import TaskState, AgentMessage
from .db_adapter import AgentDBAdapter
from .config import AgentConfig


class TaskManager:
    def __init__(self, db: AgentDBAdapter):
        self._db = db
        self._recover_stale_tasks()

    def _recover_stale_tasks(self):
        recovered = self._db.recover_stale_tasks(stale_minutes=10)
        if recovered:
            print(f"[AGENTS] Recovered {len(recovered)} stale tasks on startup")

    def create_task(self, description: str, priority: str = "normal",
                    approval_mode: str = "review", model_override: str = None) -> TaskState:
        sanitized = AgentConfig.sanitize_task_description(description)
        cost_estimate = AgentConfig.estimate_task_cost(model_override)

        task = TaskState(
            description=sanitized,
            priority=priority,
            approval_mode=approval_mode,
            model_override=model_override,
            cost_estimate=cost_estimate,
        )
        self._db.save_task(task)
        return task

    def start_task(self, task_id: str):
        self._db.update_task_status(
            task_id, "in_progress",
            started_at=datetime.now(timezone.utc).isoformat(),
            current_phase="orchestration",
        )

    def update_phase(self, task_id: str, phase: str):
        self._db.update_task_status(task_id, "in_progress", current_phase=phase)

    def await_approval(self, task_id: str):
        self._db.update_task_status(task_id, "awaiting_approval", current_phase="awaiting_approval")

    def approve_task(self, task_id: str) -> bool:
        task = self._db.get_task(task_id)
        if not task or task.status != "awaiting_approval":
            return False
        self._db.update_task_status(task_id, "in_progress", current_phase="development")
        return True

    def reject_task(self, task_id: str, reason: str = "") -> bool:
        task = self._db.get_task(task_id)
        if not task or task.status != "awaiting_approval":
            return False
        self._db.update_task_status(
            task_id, "failed",
            error_message=f"Rejected: {reason}" if reason else "Rejected by user",
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        return True

    def complete_task(self, task_id: str, result_summary: str = "",
                      git_branch: str = None, git_commit_sha: str = None,
                      actual_cost: dict = None):
        self._db.update_task_status(
            task_id, "complete",
            completed_at=datetime.now(timezone.utc).isoformat(),
            result_summary=result_summary,
            git_branch=git_branch,
            git_commit_sha=git_commit_sha,
            actual_cost=actual_cost,
        )

    def fail_task(self, task_id: str, error: str):
        self._db.update_task_status(
            task_id, "failed",
            error_message=error,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

    def cancel_task(self, task_id: str) -> bool:
        task = self._db.get_task(task_id)
        if not task or task.status in ("complete", "cancelled"):
            return False
        self._db.update_task_status(
            task_id, "cancelled",
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        return True

    def get_task(self, task_id: str) -> Optional[TaskState]:
        return self._db.get_task(task_id)

    def list_tasks(self, status: str = None, limit: int = 20) -> List[TaskState]:
        return self._db.list_tasks(status=status, limit=limit)
