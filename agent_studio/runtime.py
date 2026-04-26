"""
Agent Runtime — manages agent lifecycle, threading, and task execution pipeline.
Full 6-agent pipeline: Orchestrator → Architect → Developer → Tester → Reviewer → DevOps
with retry loops, human approval gate, budget ceiling, rollback, and version bumping.
"""
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Dict
from .agent_types import AgentMessage, AgentState
from .bus import MessageBus
from .db_adapter import AgentDBAdapter
from .task_manager import TaskManager
from .config import AgentConfig
from .auth_manager import AuthManager
from .rollback_manager import RollbackManager
from .version_manager import VersionManager
from .tools.file_tools import FileTools
from .tools.git_tools import GitTools
from .tools.test_tools import TestTools
from .tools.validation_tools import ValidationTools
from .agents.orchestrator import OrchestratorAgent
from .agents.architect import ArchitectAgent
from .agents.developer import DeveloperAgent
from .agents.tester import TesterAgent
from .agents.reviewer import CodeReviewerAgent
from .agents.devops import DevOpsAgent


class AgentRuntime:
    def __init__(self):
        self._db = AgentDBAdapter()
        self._bus = MessageBus(self._db)
        self._task_manager = TaskManager(self._db)
        self._auth = AuthManager(self._db)
        self._executor = ThreadPoolExecutor(
            max_workers=AgentConfig.THREAD_POOL_SIZE,
            thread_name_prefix="agent",
        )
        self._file_tools = FileTools()
        self._git_tools = GitTools()
        self._test_tools = TestTools()
        self._validation_tools = ValidationTools()
        self._rollback = RollbackManager()
        self._version = VersionManager()

        from .agents.base import BaseAgent
        BaseAgent.set_auth_manager(self._auth)

        self._agents = self._create_agents()
        self._running_tasks: Dict[str, bool] = {}
        self._init_agent_states()

    def _create_agents(self) -> dict:
        return {
            "orchestrator": OrchestratorAgent(
                self._bus, tools=[self._file_tools]
            ),
            "architect": ArchitectAgent(
                self._bus, tools=[self._file_tools]
            ),
            "developer": DeveloperAgent(
                self._bus, tools=[self._file_tools, self._git_tools]
            ),
            "tester": TesterAgent(
                self._bus, tools=[self._file_tools, self._test_tools]
            ),
            "reviewer": CodeReviewerAgent(
                self._bus, tools=[self._file_tools, self._validation_tools]
            ),
            "devops": DevOpsAgent(
                self._bus, tools=[self._git_tools, self._file_tools]
            ),
        }

    def _init_agent_states(self):
        for name in AgentConfig.AGENTS:
            state = AgentState(name=name)
            self._bus.publish_state(state)

    @property
    def auth(self) -> AuthManager:
        return self._auth

    @property
    def bus(self) -> MessageBus:
        return self._bus

    @property
    def task_manager(self) -> TaskManager:
        return self._task_manager

    @property
    def db(self) -> AgentDBAdapter:
        return self._db

    def submit_task(self, description: str, priority: str = "normal",
                    approval_mode: str = "review", model_override: str = None) -> dict:
        task = self._task_manager.create_task(
            description=description,
            priority=priority,
            approval_mode=approval_mode,
            model_override=model_override,
        )

        self._emit_system(task.id, f"Task created: {task.description[:100]}")
        self._executor.submit(self._run_pipeline, task.id)

        return {
            "task_id": task.id,
            "status": "pending",
            "cost_estimate": task.cost_estimate,
        }

    def approve_task(self, task_id: str) -> bool:
        if self._task_manager.approve_task(task_id):
            self._emit_system(task_id, "Task approved — resuming pipeline from development")
            self._executor.submit(self._resume_after_approval, task_id)
            return True
        return False

    def reject_task(self, task_id: str, reason: str = "") -> bool:
        return self._task_manager.reject_task(task_id, reason)

    def cancel_task(self, task_id: str) -> bool:
        self._running_tasks.pop(task_id, None)
        return self._task_manager.cancel_task(task_id)

    def rollback_task(self, task_id: str) -> dict:
        task = self._task_manager.get_task(task_id)
        if not task:
            return {"success": False, "error": "Task not found"}
        if task.status != "complete":
            return {"success": False, "error": "Can only rollback completed tasks"}
        if not task.git_commit_sha or not task.git_branch:
            return {"success": False, "error": "No commit SHA or branch recorded for this task"}

        result = self._rollback.rollback_commit(task.git_commit_sha, task.git_branch)
        if result["success"]:
            self._emit_system(task_id,
                f"Rolled back commit {task.git_commit_sha[:8]} on {task.git_branch}")
            self._db.update_task_status(task_id, "complete",
                result_summary=f"ROLLED BACK: {task.result_summary or ''}")
        return result

    def get_agent_states(self) -> Dict[str, dict]:
        states = self._db.get_agent_states()
        result = {}
        for name in AgentConfig.AGENTS:
            if name in states:
                result[name] = states[name].to_dict()
            else:
                result[name] = AgentState(name=name).to_dict()
        return result

    # ── Full Pipeline ──

    def _run_pipeline(self, task_id: str):
        self._running_tasks[task_id] = True
        try:
            task = self._task_manager.get_task(task_id)
            if not task:
                return

            self._task_manager.start_task(task_id)

            # Phase 1: Orchestrator analyzes
            self._emit_system(task_id, "Pipeline started — Orchestrator analyzing task")
            self._task_manager.update_phase(task_id, "orchestration")
            orchestrator = self._agents["orchestrator"]
            plan_result = orchestrator.plan_task(task_id, task.description)
            if self._check_abort(task_id, plan_result):
                return

            # Phase 2: Architect designs solution
            self._emit_system(task_id, "Orchestrator done — Architect designing solution")
            self._task_manager.update_phase(task_id, "architecture")
            architect = self._agents["architect"]
            arch_result = architect.design(task_id, task.description)
            if self._check_abort(task_id, arch_result):
                return

            # Approval gate (if mode is "review" or "strict")
            if task.approval_mode in ("review", "strict"):
                self._emit_system(task_id, "Architect plan ready — awaiting your approval")
                self._bus.publish(AgentMessage(
                    from_agent="architect",
                    to_agent="user",
                    message_type="approval_required",
                    task_id=task_id,
                    content=f"Review the architect's plan before proceeding:\n\n{arch_result.content[:1000]}",
                    metadata=arch_result.metadata,
                ))
                self._task_manager.await_approval(task_id)
                return  # Pipeline pauses — resumed via approve_task()

            # If auto mode, continue directly
            self._continue_after_architecture(task_id, arch_result)

        except Exception as e:
            self._task_manager.fail_task(task_id, f"Pipeline error: {str(e)}")
            self._emit_system(task_id, f"Pipeline failed: {str(e)}")
            print(f"[AGENTS] Pipeline error for task {task_id}: {traceback.format_exc()}")
        finally:
            if task_id not in self._running_tasks:
                self._reset_agents()

    def _resume_after_approval(self, task_id: str):
        self._running_tasks[task_id] = True
        try:
            messages = self._bus.get_messages(task_id)
            arch_msg = None
            for msg in reversed(messages):
                if msg.from_agent == "architect" and msg.message_type == "handoff":
                    arch_msg = msg
                    break

            if not arch_msg:
                self._task_manager.fail_task(task_id, "No architect plan found to resume from")
                return

            self._continue_after_architecture(task_id, arch_msg)

        except Exception as e:
            self._task_manager.fail_task(task_id, f"Pipeline error: {str(e)}")
            self._emit_system(task_id, f"Pipeline failed after approval: {str(e)}")
            print(f"[AGENTS] Pipeline error for task {task_id}: {traceback.format_exc()}")
        finally:
            self._running_tasks.pop(task_id, None)
            self._reset_agents()

    def _continue_after_architecture(self, task_id: str, arch_result: AgentMessage):
        task = self._task_manager.get_task(task_id)

        # Phase 3-5: Developer writes code (with retry loop from Tester/Reviewer)
        dev_result = self._development_loop(task_id, arch_result)
        if dev_result is None:
            return

        # Phase 6: DevOps deploys
        self._emit_system(task_id, "All checks passed — DevOps deploying changes")
        self._task_manager.update_phase(task_id, "deployment")

        # Conflict detection before deploy
        branch_name = f"{AgentConfig.AGENT_BRANCH_PREFIX}{task_id[:8]}"
        conflicts = self._version.check_upstream_conflicts(branch_name)
        if conflicts.get("has_conflicts"):
            conflict_files = ", ".join(conflicts.get("conflicting_files", [])[:5])
            self._task_manager.fail_task(task_id,
                f"Upstream conflict detected on {len(conflicts.get('conflicting_files', []))} file(s): {conflict_files}")
            self._emit_system(task_id, f"Conflict detected: {conflicts['reason']}")
            return

        devops = self._agents["devops"]
        deploy_result = devops.deploy(task_id, dev_result)

        if deploy_result.message_type == "error":
            self._task_manager.fail_task(task_id, deploy_result.content)
            self._emit_system(task_id, f"Deployment failed: {deploy_result.content[:200]}")
            return

        # SemVer bump based on commit message
        commit_msg = deploy_result.content[:200] if deploy_result.content else "fix: agent changes"
        version_info = self._version.bump_version(commit_msg)
        tag_result = self._version.create_version_tag(version_info)
        version_str = None
        if tag_result.get("success"):
            version_str = tag_result["version"]
            self._emit_system(task_id,
                f"Version bumped: v{version_info['previous']} -> v{version_info['new']} ({version_info['bump_type']})")

        commit_sha = deploy_result.metadata.get("commit_sha", "")

        total_cost = self._calculate_total_cost(task_id)
        self._task_manager.complete_task(
            task_id,
            result_summary=deploy_result.content[:500],
            actual_cost=total_cost,
            git_branch=branch_name,
            git_commit_sha=commit_sha,
        )
        if version_str:
            self._db.update_task_status(task_id, "complete", version=version_str)

        self._emit_system(task_id,
            f"Task complete! Version: {version_str or 'N/A'} | Cost: ${total_cost.get('total', 0):.4f}")

    def _development_loop(self, task_id: str, plan: AgentMessage):
        """Developer → Tester → Reviewer loop with max 2 revision rounds."""
        developer = self._agents["developer"]
        tester = self._agents["tester"]
        reviewer = self._agents["reviewer"]

        revision_context = plan
        max_rounds = AgentConfig.MAX_REVISION_ROUNDS

        for round_num in range(max_rounds + 1):
            if not self._running_tasks.get(task_id):
                return None

            # Developer writes code
            round_label = f" (revision {round_num})" if round_num > 0 else ""
            self._emit_system(task_id, f"Developer writing code{round_label}")
            self._task_manager.update_phase(task_id, "development")
            dev_result = developer.develop(task_id, revision_context)
            if self._check_abort(task_id, dev_result):
                return None

            # Tester runs tests
            self._emit_system(task_id, "Developer done — Tester validating changes")
            self._task_manager.update_phase(task_id, "testing")
            test_result = tester.test(task_id, dev_result)
            if self._check_abort(task_id, test_result):
                return None

            test_passed = "fail" not in test_result.content.lower() or "0 failed" in test_result.content.lower()
            if not test_passed and round_num < max_rounds:
                self._emit_system(task_id, f"Tests failed — sending back to Developer (round {round_num + 1}/{max_rounds})")
                revision_context = AgentMessage(
                    from_agent="tester",
                    to_agent="developer",
                    message_type="retry",
                    task_id=task_id,
                    content=f"Tests failed. Fix these issues and try again:\n\n{test_result.content}",
                    metadata=test_result.metadata,
                )
                continue
            elif not test_passed:
                self._task_manager.fail_task(task_id, f"Tests still failing after {max_rounds} revision rounds")
                self._emit_system(task_id, "Tests failed after maximum retries — task failed")
                return None

            # Code Reviewer checks quality
            self._emit_system(task_id, "Tests passed — Code Reviewer checking quality")
            self._task_manager.update_phase(task_id, "review")
            review_result = reviewer.review(task_id, dev_result, test_result)
            if self._check_abort(task_id, review_result):
                return None

            approved = "approve" in review_result.content.lower() and "request_changes" not in review_result.content.lower()
            if not approved and round_num < max_rounds:
                self._emit_system(task_id, f"Review requested changes — sending back to Developer (round {round_num + 1}/{max_rounds})")
                revision_context = AgentMessage(
                    from_agent="reviewer",
                    to_agent="developer",
                    message_type="retry",
                    task_id=task_id,
                    content=f"Code review requested changes:\n\n{review_result.content}",
                    metadata=review_result.metadata,
                )
                continue
            elif not approved:
                self._task_manager.fail_task(task_id, f"Code review still not approved after {max_rounds} rounds")
                self._emit_system(task_id, "Review not approved after maximum retries — task failed")
                return None

            # All checks passed
            self._emit_system(task_id, "Code review APPROVED")
            return dev_result

        return None

    # ── Helpers ──

    def _check_abort(self, task_id: str, result: AgentMessage) -> bool:
        if not self._running_tasks.get(task_id):
            return True
        if result.message_type == "error":
            self._task_manager.fail_task(task_id, result.content)
            self._emit_system(task_id, f"Agent error: {result.content[:200]}")
            return True
        return False

    def _calculate_total_cost(self, task_id: str) -> dict:
        messages = self._bus.get_messages(task_id)
        total = 0.0
        by_agent = {}
        for msg in messages:
            cost = msg.metadata.get("cost_usd", 0)
            if cost:
                total += cost
                by_agent[msg.from_agent] = by_agent.get(msg.from_agent, 0) + cost
        return {"total": round(total, 4), "by_agent": by_agent, "currency": "USD"}

    def _emit_system(self, task_id: str, content: str):
        msg = AgentMessage(
            from_agent="system",
            to_agent="broadcast",
            message_type="status",
            task_id=task_id,
            content=content,
        )
        self._bus.publish(msg)

    def _reset_agents(self):
        for agent in self._agents.values():
            agent.reset()

    def shutdown(self):
        self._running_tasks.clear()
        self._executor.shutdown(wait=False)
