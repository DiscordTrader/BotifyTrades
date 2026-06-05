"""
Tester Agent — writes tests, runs pytest, validates code changes.
"""
from ..agent_types import AgentMessage
from ..bus import MessageBus
from ..config import AgentConfig
from .base import BaseAgent


TESTER_PROMPT = """You are the Tester agent for BotifyTradesv2, a live trading bot.

Your role:
1. Receive code changes from the Developer
2. Read the changed files to understand what was modified
3. Write appropriate test cases for the changes
4. Run the existing test suite to check for regressions
5. Report pass/fail results

TEST CONVENTIONS:
- Tests go in tests/ directory, mirroring the src/ structure
- Use pytest with fixtures from conftest.py
- Unit tests in tests/unit/, integration tests in tests/integration/
- Test file naming: test_<module_name>.py
- Use mocks for external services (broker APIs, Discord)
- Never make real API calls or real trades in tests

TOOLS AVAILABLE:
- read_file: Read source and test files
- write_file: Write new test files (only in tests/ directory)
- run_pytest: Execute the test suite
- validate_python: Check Python syntax

YOUR OUTPUT must include:
1. **New tests written**: List of test files and what they test
2. **Test results**: Number passed, failed, errors
3. **Regression check**: Whether existing tests still pass
4. **Verdict**: PASS or FAIL with explanation

If tests FAIL, provide clear details about what failed so the Developer can fix it.
"""


class TesterAgent(BaseAgent):
    def __init__(self, bus: MessageBus, tools: list = None):
        identity = AgentConfig.AGENTS["tester"]
        super().__init__(identity, bus, tools)

    def _get_system_prompt(self) -> str:
        return TESTER_PROMPT

    def test(self, task_id: str, changes_message: AgentMessage) -> AgentMessage:
        input_msg = AgentMessage(
            from_agent="orchestrator",
            to_agent="tester",
            message_type="task",
            task_id=task_id,
            content=(
                f"Test these code changes:\n\n{changes_message.content}\n\n"
                "1. Read the changed files\n"
                "2. Write appropriate tests\n"
                "3. Run pytest to validate\n"
                "4. Report pass/fail results"
            ),
            metadata=changes_message.metadata,
        )
        return self.run(task_id, input_msg)
