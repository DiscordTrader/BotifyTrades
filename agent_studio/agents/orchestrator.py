"""
Orchestrator Agent — receives tasks, routes to other agents, handles failures.
"""
import json
from ..agent_types import AgentMessage, TaskState
from ..bus import MessageBus
from ..config import AgentConfig
from .base import BaseAgent


ORCHESTRATOR_PROMPT = """You are the Orchestrator agent for BotifyTradesv2, a live trading bot.

Your role:
1. Receive a task description from the user
2. Analyze the task to understand what needs to be done
3. Create a clear, actionable plan for the Developer agent
4. Route the plan to the Developer

You do NOT write code. You decompose tasks and create clear instructions.

When creating instructions for the Developer, include:
- Which files likely need to be modified (use your tools to check the codebase)
- What the expected behavior change is
- Any risks or special considerations (this is a LIVE TRADING system)

Output your plan as a structured message that the Developer can act on.

IMPORTANT RULES:
- This is a live trading bot. Code changes affect real money.
- Never suggest modifying files outside of src/, gui_app/, tests/, docs/, scripts/
- Always mention if changes touch risk management or broker code
- Flag any changes that could affect order execution
"""


class OrchestratorAgent(BaseAgent):
    def __init__(self, bus: MessageBus, tools: list = None):
        identity = AgentConfig.AGENTS["orchestrator"]
        super().__init__(identity, bus, tools)

    def _get_system_prompt(self) -> str:
        return ORCHESTRATOR_PROMPT

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
        return task

    def plan_task(self, task_id: str, description: str) -> AgentMessage:
        input_msg = AgentMessage(
            from_agent="user",
            to_agent="orchestrator",
            message_type="task",
            task_id=task_id,
            content=f"Plan this task for the Developer agent:\n\n{description}",
        )
        return self.run(task_id, input_msg)
