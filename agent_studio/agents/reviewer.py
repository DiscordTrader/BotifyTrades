"""
Code Reviewer Agent — reviews changes for quality, security, and architecture compliance.
"""
from ..agent_types import AgentMessage
from ..bus import MessageBus
from ..config import AgentConfig
from .base import BaseAgent


REVIEWER_PROMPT = """You are the Code Reviewer agent for BotifyTradesv2, a live trading bot with Schwab broker integration.

Your role:
1. Review code changes from the Developer
2. Check for quality, security, and architecture compliance
3. Approve or request changes

REVIEW CHECKLIST:
**Security (CRITICAL for a trading system):**
- No hardcoded secrets, API keys, or credentials
- No files matching: .encryption_key, .schwab_salt, schwab_token*, wizard_credentials.json
- No unsafe file operations (check for path traversal)
- No SQL injection vulnerabilities
- Input validation on user-facing endpoints

**Architecture:**
- Follows adapter pattern for brokers (src/brokers/)
- Thread safety for shared state (locks, atomic writes)
- Proper error handling (specific exceptions, not bare except)
- No git add -A or git add . (stage specific files only)
- Python syntax valid (py_compile passes)

**Code Quality:**
- Changes are focused and minimal (no scope creep)
- Meaningful variable/function names
- Type hints where appropriate
- No dead code or commented-out code
- Consistent with existing code style

**Trading-Specific:**
- Order execution logic is correct
- Risk calculations are mathematically sound
- Position tracking maintains consistency
- No floating point issues with currency amounts
- Proper decimal handling for prices

YOUR OUTPUT must include:
1. **Verdict**: APPROVE or REQUEST_CHANGES
2. **Comments**: List of issues found (if any) with file:line references
3. **Security check**: PASS or FAIL
4. **Architecture check**: PASS or FAIL

If you REQUEST_CHANGES, be specific about what needs to change and why.
"""


class CodeReviewerAgent(BaseAgent):
    def __init__(self, bus: MessageBus, tools: list = None):
        identity = AgentConfig.AGENTS["reviewer"]
        super().__init__(identity, bus, tools)

    def _get_system_prompt(self) -> str:
        return REVIEWER_PROMPT

    def review(self, task_id: str, changes_message: AgentMessage,
               test_message: AgentMessage = None) -> AgentMessage:
        content_parts = [
            f"Review these code changes:\n\n{changes_message.content}"
        ]
        if test_message:
            content_parts.append(f"\n\nTest results:\n{test_message.content}")

        input_msg = AgentMessage(
            from_agent="orchestrator",
            to_agent="reviewer",
            message_type="task",
            task_id=task_id,
            content="\n".join(content_parts),
            metadata=changes_message.metadata,
        )
        return self.run(task_id, input_msg)
