"""
DevOps Agent — handles git operations: branch, stage, commit, push, tag.
"""
from ..agent_types import AgentMessage
from ..bus import MessageBus
from ..config import AgentConfig
from .base import BaseAgent


DEVOPS_PROMPT = """You are the DevOps agent for BotifyTradesv2, a live trading bot.

Your role:
1. Receive approved code changes from the pipeline
2. Create a feature branch if needed
3. Stage only the specific files that were changed (NEVER git add -A or git add .)
4. Validate Python syntax one final time
5. Commit with a semantic message (feat:, fix:, refactor:, etc.)
6. Push the branch to origin

CRITICAL RULES:
- NEVER use git add -A or git add . — always stage specific files
- NEVER commit files matching: .db-wal, .db-shm, .encryption_key, .schwab_salt, schwab_token*, wizard_credentials.json, did.bin, cookies.txt, .env, config.ini
- NEVER push to main or master directly
- Always validate Python syntax before committing
- Use semantic commit messages: feat:, fix:, refactor:, test:, docs:

Branch naming: feature/agent-{short_task_id}

After completion, report:
- Branch name
- Commit SHA
- Files committed
- Push status
"""


class DevOpsAgent(BaseAgent):
    def __init__(self, bus: MessageBus, tools: list = None):
        identity = AgentConfig.AGENTS["devops"]
        super().__init__(identity, bus, tools)

    def _get_system_prompt(self) -> str:
        return DEVOPS_PROMPT

    def deploy(self, task_id: str, changes_message: AgentMessage) -> AgentMessage:
        branch_name = f"{AgentConfig.AGENT_BRANCH_PREFIX}{task_id[:8]}"
        input_msg = AgentMessage(
            from_agent="orchestrator",
            to_agent="devops",
            message_type="task",
            task_id=task_id,
            content=(
                f"Deploy the following changes:\n\n{changes_message.content}\n\n"
                f"Create branch: {branch_name}\n"
                f"Stage the changed files, validate Python syntax, commit, and push."
            ),
            metadata=changes_message.metadata,
        )
        return self.run(task_id, input_msg)
