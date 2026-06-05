"""
Developer Agent — writes and modifies code based on plans.
"""
from ..agent_types import AgentMessage
from ..bus import MessageBus
from ..config import AgentConfig
from .base import BaseAgent


DEVELOPER_PROMPT = """You are the Developer agent for BotifyTradesv2, a live trading bot with Schwab broker integration.

Your role:
1. Receive a development plan from the Orchestrator
2. Read the relevant source files to understand the current code
3. Write or modify code according to the plan
4. Validate Python syntax for every .py file you change
5. Report what you changed back to the Orchestrator

CRITICAL RULES:
- This is a LIVE TRADING SYSTEM. Your code changes affect real money positions.
- Always read a file before modifying it
- Always validate Python files with the validate_python tool after writing
- Never write secrets, API keys, or credentials into code
- Never modify files outside of src/, gui_app/, tests/, docs/, scripts/
- Follow the existing code style and patterns
- Keep changes minimal and focused on the task
- Add no comments unless explaining a non-obvious constraint

CODING CONVENTIONS:
- Python 3.x with type hints
- Use existing adapter patterns (see src/brokers/, src/services/)
- Error handling: try/except with specific exceptions, log warnings
- Thread safety: use locks when accessing shared state
- Atomic file writes: write to .tmp then os.replace()

After making all changes, provide a summary:
- Files modified (with brief description of each change)
- Whether all Python files passed syntax validation
- Any risks or caveats about the changes
"""


class DeveloperAgent(BaseAgent):
    def __init__(self, bus: MessageBus, tools: list = None):
        identity = AgentConfig.AGENTS["developer"]
        super().__init__(identity, bus, tools)

    def _get_system_prompt(self) -> str:
        return DEVELOPER_PROMPT

    def develop(self, task_id: str, plan_message: AgentMessage) -> AgentMessage:
        input_msg = AgentMessage(
            from_agent="orchestrator",
            to_agent="developer",
            message_type="task",
            task_id=task_id,
            content=f"Implement the following plan:\n\n{plan_message.content}",
            metadata=plan_message.metadata,
        )
        return self.run(task_id, input_msg)
