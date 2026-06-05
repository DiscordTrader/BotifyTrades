"""
Test execution tools for the Tester agent.
Runs pytest and parses results.
"""
import os
import subprocess
from ..config import AgentConfig


class TestTools:
    def __init__(self, repo_root: str = None):
        self._root = repo_root or AgentConfig.get_repo_root()

    def run_pytest(self, target: str = "tests/", extra_args: str = "") -> dict:
        cmd = ["python", "-m", "pytest", target, "-x", "--tb=short", "-q"]
        if extra_args:
            cmd.extend(extra_args.split())
        try:
            result = subprocess.run(
                cmd, cwd=self._root, capture_output=True, text=True, timeout=120,
            )
            output = result.stdout + "\n" + result.stderr
            passed = failed = errors = 0
            for line in output.split("\n"):
                line = line.strip()
                if "passed" in line or "failed" in line or "error" in line:
                    import re
                    m_passed = re.search(r'(\d+) passed', line)
                    m_failed = re.search(r'(\d+) failed', line)
                    m_errors = re.search(r'(\d+) error', line)
                    if m_passed:
                        passed = int(m_passed.group(1))
                    if m_failed:
                        failed = int(m_failed.group(1))
                    if m_errors:
                        errors = int(m_errors.group(1))

            return {
                "success": result.returncode == 0,
                "passed": passed,
                "failed": failed,
                "errors": errors,
                "output": output[:5000],
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "pytest timed out after 120s",
                    "passed": 0, "failed": 0, "errors": 0, "output": ""}
        except Exception as e:
            return {"success": False, "error": str(e),
                    "passed": 0, "failed": 0, "errors": 0, "output": ""}

    def run_single_test(self, test_file: str) -> dict:
        return self.run_pytest(target=test_file)

    def get_tool_definitions(self) -> list:
        return [
            {
                "name": "run_pytest",
                "description": "Run pytest on a test directory or file. Returns pass/fail counts and output.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string", "description": "Test path (default: tests/)", "default": "tests/"},
                        "extra_args": {"type": "string", "description": "Extra pytest args (e.g. '-k test_name')", "default": ""}
                    },
                    "required": []
                }
            },
        ]

    def execute_tool(self, name: str, args: dict) -> dict:
        if name == "run_pytest":
            return self.run_pytest(
                target=args.get("target", "tests/"),
                extra_args=args.get("extra_args", ""),
            )
        return {"success": False, "error": f"Unknown tool: {name}"}
