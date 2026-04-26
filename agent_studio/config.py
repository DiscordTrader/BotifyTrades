"""
Agent system configuration.
Loads API keys from environment, defines agent identities and defaults.
"""
import os
from .agent_types import AgentIdentity


class AgentConfig:
    ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"

    DEFAULT_MODEL = "claude-sonnet-4-20250514"
    ARCHITECT_MODEL = "claude-sonnet-4-20250514"

    MAX_TASK_TIMEOUT = 600
    MAX_RETRIES_PER_AGENT = 3
    MAX_REVISION_ROUNDS = 2
    TASK_DESCRIPTION_MAX_LENGTH = 500

    DEFAULT_BUDGET_USD = 2.00

    THREAD_POOL_SIZE = 8
    MAX_SSE_CLIENTS = 5
    SSE_KEEPALIVE_SECONDS = 15

    DB_FILENAME = "agent_data.db"

    AGENT_BRANCH_PREFIX = "feature/agent-"

    SAFE_WRITE_DIRS = ["src/", "gui_app/", "tests/", "docs/", "scripts/"]
    BLOCKED_READ_PATTERNS = [
        ".env", ".encryption_key", ".schwab_salt",
        "schwab_token", "wizard_credentials",
        "did.bin", "cookies.txt", "config.ini",
    ]
    SAFE_FILE_EXTENSIONS = {
        ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css",
        ".sh", ".bat", ".md", ".txt", ".yml", ".yaml",
        ".ini", ".toml", ".cfg", ".svg",
    }
    NEVER_COMMIT_PATTERNS = [
        ".db-wal", ".db-shm", ".position_cache.json",
        ".encryption_key", ".schwab_salt", "schwab_token",
        "wizard_credentials.json", "did.bin", "cookies.txt",
        ".env", "config.ini",
    ]

    AGENTS = {
        "orchestrator": AgentIdentity(
            name="orchestrator",
            display_name="Orchestrator",
            color="#0FF0B3",
            model=DEFAULT_MODEL,
            timeout_seconds=60,
        ),
        "architect": AgentIdentity(
            name="architect",
            display_name="Architect",
            color="#7C3AED",
            model=ARCHITECT_MODEL,
            timeout_seconds=120,
        ),
        "developer": AgentIdentity(
            name="developer",
            display_name="Developer",
            color="#3B82F6",
            model=DEFAULT_MODEL,
            timeout_seconds=180,
        ),
        "tester": AgentIdentity(
            name="tester",
            display_name="Tester",
            color="#F59E0B",
            model=DEFAULT_MODEL,
            timeout_seconds=120,
        ),
        "reviewer": AgentIdentity(
            name="reviewer",
            display_name="Code Reviewer",
            color="#EF4444",
            model=DEFAULT_MODEL,
            timeout_seconds=90,
        ),
        "devops": AgentIdentity(
            name="devops",
            display_name="DevOps",
            color="#10B981",
            model=DEFAULT_MODEL,
            timeout_seconds=60,
        ),
    }

    SONNET_INPUT_COST_PER_1K = 0.003
    SONNET_OUTPUT_COST_PER_1K = 0.015
    OPUS_INPUT_COST_PER_1K = 0.015
    OPUS_OUTPUT_COST_PER_1K = 0.075

    @classmethod
    def get_api_key(cls) -> str:
        key = os.environ.get(cls.ANTHROPIC_API_KEY_ENV, "")
        if not key:
            raise ValueError(
                "No authentication configured. Use OAuth (recommended) or set "
                "ANTHROPIC_API_KEY in your .env file. Configure in the dashboard Settings panel."
            )
        return key

    @classmethod
    def get_repo_root(cls) -> str:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    @classmethod
    def get_db_path(cls) -> str:
        return os.path.join(cls.get_repo_root(), cls.DB_FILENAME)

    @classmethod
    def estimate_cost(cls, model: str, input_tokens: int, output_tokens: int) -> float:
        if "opus" in model:
            return (input_tokens / 1000 * cls.OPUS_INPUT_COST_PER_1K +
                    output_tokens / 1000 * cls.OPUS_OUTPUT_COST_PER_1K)
        return (input_tokens / 1000 * cls.SONNET_INPUT_COST_PER_1K +
                output_tokens / 1000 * cls.SONNET_OUTPUT_COST_PER_1K)

    @classmethod
    def estimate_task_cost(cls, model_override: str = None) -> dict:
        model = model_override or cls.DEFAULT_MODEL
        if "opus" in model:
            return {"min": 1.50, "max": 5.00, "currency": "USD"}
        return {"min": 0.15, "max": 0.40, "currency": "USD"}

    @classmethod
    def sanitize_task_description(cls, description: str) -> str:
        import re
        cleaned = re.sub(r'```[\s\S]*?```', '[code block removed]', description)
        cleaned = re.sub(r'`[^`]+`', '[code removed]', cleaned)
        return cleaned[:cls.TASK_DESCRIPTION_MAX_LENGTH].strip()

    @classmethod
    def scrub_secrets(cls, text: str) -> str:
        api_key = os.environ.get(cls.ANTHROPIC_API_KEY_ENV, "")
        if api_key and api_key in text:
            text = text.replace(api_key, "[REDACTED]")
        for env_var in ["SCHWAB_APP_KEY", "SCHWAB_APP_SECRET", "FLASK_SECRET_KEY"]:
            val = os.environ.get(env_var, "")
            if val and len(val) > 8 and val in text:
                text = text.replace(val, "[REDACTED]")
        return text
