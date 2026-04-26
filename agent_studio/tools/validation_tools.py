"""
Validation tools for the Code Reviewer agent.
Checks Python syntax, architecture rules, and security patterns.
"""
import os
import re
import subprocess
from typing import List, Dict
from ..config import AgentConfig


class ValidationTools:
    def __init__(self, repo_root: str = None):
        self._root = repo_root or AgentConfig.get_repo_root()

    def validate_python_syntax(self, filepath: str) -> dict:
        abs_path = os.path.join(self._root, filepath)
        if not os.path.isfile(abs_path):
            return {"success": False, "error": f"File not found: {filepath}"}
        try:
            result = subprocess.run(
                ["python", "-m", "py_compile", abs_path],
                capture_output=True, text=True, timeout=10,
            )
            return {
                "success": result.returncode == 0,
                "file": filepath,
                "error": result.stderr.strip() if result.returncode != 0 else "",
            }
        except Exception as e:
            return {"success": False, "file": filepath, "error": str(e)}

    def check_security(self, filepath: str) -> dict:
        abs_path = os.path.join(self._root, filepath)
        if not os.path.isfile(abs_path):
            return {"success": False, "error": f"File not found: {filepath}"}
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            return {"success": False, "error": str(e)}

        issues = []

        secret_patterns = [
            (r'(?:api_key|apikey|secret|password|token)\s*=\s*["\'][^"\']{8,}["\']', "Possible hardcoded secret"),
            (r'sk-[a-zA-Z0-9]{20,}', "Possible API key (sk-...)"),
            (r'AKIA[0-9A-Z]{16}', "Possible AWS access key"),
        ]
        for pattern, desc in secret_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for m in matches:
                line_num = content[:m.start()].count("\n") + 1
                issues.append({"line": line_num, "severity": "HIGH", "message": desc})

        dangerous_patterns = [
            (r'os\.system\(', "Use subprocess instead of os.system"),
            (r'eval\(', "eval() is dangerous — avoid"),
            (r'exec\(', "exec() is dangerous — avoid"),
            (r'__import__\(', "Dynamic import — review carefully"),
        ]
        for pattern, desc in dangerous_patterns:
            matches = re.finditer(pattern, content)
            for m in matches:
                line_num = content[:m.start()].count("\n") + 1
                issues.append({"line": line_num, "severity": "MEDIUM", "message": desc})

        return {
            "success": len(issues) == 0,
            "file": filepath,
            "issues": issues,
            "issue_count": len(issues),
        }

    def check_architecture(self, filepath: str) -> dict:
        abs_path = os.path.join(self._root, filepath)
        if not os.path.isfile(abs_path):
            return {"success": False, "error": f"File not found: {filepath}"}
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            return {"success": False, "error": str(e)}

        issues = []

        if "git add -A" in content or "git add ." in content:
            issues.append({"severity": "CRITICAL", "message": "Contains 'git add -A' or 'git add .' — must stage specific files"})

        for blocked in AgentConfig.NEVER_COMMIT_PATTERNS:
            if blocked in content and not filepath.endswith(("config.py", "git_tools.py", "autosave.sh", ".gitignore")):
                issues.append({"severity": "MEDIUM", "message": f"References blocked pattern '{blocked}' — verify not committing secrets"})

        if re.search(r'except\s*:', content):
            line_matches = [(content[:m.start()].count("\n") + 1) for m in re.finditer(r'except\s*:', content)]
            for ln in line_matches[:3]:
                issues.append({"severity": "LOW", "message": f"Bare except at line {ln} — use specific exception"})

        return {
            "success": len([i for i in issues if i["severity"] in ("CRITICAL", "HIGH")]) == 0,
            "file": filepath,
            "issues": issues,
            "issue_count": len(issues),
        }

    def get_tool_definitions(self) -> list:
        return [
            {
                "name": "validate_syntax",
                "description": "Validate Python syntax for a file using py_compile.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "filepath": {"type": "string", "description": "Python file path relative to repo"}
                    },
                    "required": ["filepath"]
                }
            },
            {
                "name": "check_security",
                "description": "Scan a file for security issues (hardcoded secrets, dangerous functions).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "filepath": {"type": "string", "description": "File path to scan"}
                    },
                    "required": ["filepath"]
                }
            },
            {
                "name": "check_architecture",
                "description": "Check a file against BotifyTrades architecture rules.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "filepath": {"type": "string", "description": "File path to check"}
                    },
                    "required": ["filepath"]
                }
            },
        ]

    def execute_tool(self, name: str, args: dict) -> dict:
        tools = {
            "validate_syntax": lambda a: self.validate_python_syntax(a["filepath"]),
            "check_security": lambda a: self.check_security(a["filepath"]),
            "check_architecture": lambda a: self.check_architecture(a["filepath"]),
        }
        fn = tools.get(name)
        if not fn:
            return {"success": False, "error": f"Unknown tool: {name}"}
        return fn(args)
