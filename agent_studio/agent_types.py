"""
Core data types for the multi-agent system.
All agent communication uses these dataclasses.
"""
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any


@dataclass
class AgentIdentity:
    name: str
    display_name: str
    color: str
    model: str
    max_retries: int = 3
    timeout_seconds: int = 120


@dataclass
class AgentMessage:
    from_agent: str
    to_agent: str
    message_type: str
    task_id: str
    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    sequence_number: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AgentState:
    name: str
    status: str = "idle"
    current_task_id: Optional[str] = None
    progress_pct: int = 0
    last_message_id: Optional[str] = None
    started_at: Optional[str] = None
    token_usage: Dict[str, int] = field(default_factory=lambda: {"input": 0, "output": 0})

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TaskState:
    description: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "pending"
    priority: str = "normal"
    current_phase: str = ""
    approval_mode: str = "review"
    model_override: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    git_branch: Optional[str] = None
    git_commit_sha: Optional[str] = None
    version: Optional[str] = None
    error_message: Optional[str] = None
    cost_estimate: Optional[Dict[str, float]] = None
    actual_cost: Optional[Dict[str, Any]] = None
    result_summary: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ArchitecturePlan:
    files_to_create: List[Dict[str, str]] = field(default_factory=list)
    files_to_modify: List[Dict[str, str]] = field(default_factory=list)
    risk_level: str = "low"
    estimated_complexity: str = "small"
    summary: str = ""


@dataclass
class CodeChanges:
    files: List[Dict[str, Any]] = field(default_factory=list)
    syntax_valid: bool = True
    summary: str = ""


@dataclass
class TestResults:
    passed: int = 0
    failed: int = 0
    errors: int = 0
    new_tests: List[str] = field(default_factory=list)
    coverage: Optional[str] = None
    output: str = ""


@dataclass
class ReviewResult:
    verdict: str = "approve"
    comments: List[Dict[str, str]] = field(default_factory=list)
    security_check: str = "pass"
    architecture_check: str = "pass"


@dataclass
class DeployResult:
    commit_sha: str = ""
    branch: str = ""
    tag: Optional[str] = None
    version: Optional[str] = None
    push_status: str = "pending"


MESSAGE_TYPES = [
    "task", "plan", "code_change", "test_result", "review",
    "git_event", "handoff", "error", "status", "retry",
    "approval_required", "approved", "rejected",
]

TASK_STATUSES = [
    "pending", "in_progress", "awaiting_approval",
    "complete", "failed", "cancelled",
]

AGENT_STATUSES = [
    "idle", "thinking", "working", "blocked", "error", "done",
]
