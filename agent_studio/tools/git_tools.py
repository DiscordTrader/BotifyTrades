"""
Safe git operations for the DevOps agent.
Mirrors the safety rules from scripts/autosave.sh.
Acquires the autosave mutex before any git operation.
"""
import os
import subprocess
import time
from pathlib import Path
from typing import List, Optional
from ..config import AgentConfig


class GitTools:
    def __init__(self, repo_root: str = None):
        self._root = repo_root or AgentConfig.get_repo_root()
        self._mutex_dir = os.path.join(self._root, ".git", "autosave_mutex")

    def _run(self, cmd: List[str], timeout: int = 30) -> dict:
        try:
            env = os.environ.copy()
            env["GIT_TERMINAL_PROMPT"] = "0"
            result = subprocess.run(
                cmd, cwd=self._root, capture_output=True, text=True,
                timeout=timeout, env=env,
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Command timed out", "stdout": "", "stderr": ""}
        except Exception as e:
            return {"success": False, "error": str(e), "stdout": "", "stderr": ""}

    def _acquire_mutex(self) -> bool:
        try:
            os.makedirs(self._mutex_dir)
            pid_file = os.path.join(self._mutex_dir, "pid")
            with open(pid_file, "w") as f:
                f.write(str(os.getpid()))
            return True
        except FileExistsError:
            pid_file = os.path.join(self._mutex_dir, "pid")
            if os.path.exists(pid_file):
                age = time.time() - os.path.getmtime(pid_file)
                if age > 120:
                    self._release_mutex()
                    return self._acquire_mutex()
            return False

    def _release_mutex(self):
        import shutil
        try:
            shutil.rmtree(self._mutex_dir, ignore_errors=True)
        except Exception:
            pass

    def _with_mutex(self, fn):
        if not self._acquire_mutex():
            return {"success": False, "error": "Could not acquire git mutex — autosave.sh may be running"}
        try:
            return fn()
        finally:
            self._release_mutex()

    def status(self) -> dict:
        return self._run(["git", "status", "--porcelain"])

    def diff(self, cached: bool = False) -> dict:
        cmd = ["git", "diff"]
        if cached:
            cmd.append("--cached")
        return self._run(cmd)

    def current_branch(self) -> dict:
        return self._run(["git", "branch", "--show-current"])

    def create_branch(self, branch_name: str) -> dict:
        def _do():
            current = self._run(["git", "branch", "--show-current"])
            result = self._run(["git", "checkout", "-b", branch_name])
            if not result["success"]:
                existing = self._run(["git", "checkout", branch_name])
                return existing
            return result
        return self._with_mutex(_do)

    def safe_add(self, files: List[str]) -> dict:
        def _do():
            for f in files:
                for blocked in AgentConfig.NEVER_COMMIT_PATTERNS:
                    if blocked in f:
                        return {"success": False, "error": f"Blocked file: {f} matches {blocked}"}
                ext = Path(f).suffix
                if ext and ext not in AgentConfig.SAFE_FILE_EXTENSIONS:
                    return {"success": False, "error": f"Unsafe extension: {ext} in {f}"}

            added = []
            for f in files:
                result = self._run(["git", "add", "--", f])
                if result["success"]:
                    added.append(f)
                else:
                    return {"success": False, "error": f"Failed to add {f}: {result.get('stderr', '')}"}
            return {"success": True, "files_added": added}
        return self._with_mutex(_do)

    def safe_commit(self, message: str) -> dict:
        def _do():
            result = self._run(["git", "commit", "-m", message])
            return result
        return self._with_mutex(_do)

    def push(self, branch: str = None) -> dict:
        def _do():
            cmd = ["git", "push"]
            if branch:
                cmd.extend(["-u", "origin", branch])
            return self._run(cmd, timeout=60)
        return self._with_mutex(_do)

    def create_tag(self, tag_name: str, message: str = None) -> dict:
        def _do():
            if message:
                return self._run(["git", "tag", "-a", tag_name, "-m", message])
            return self._run(["git", "tag", tag_name, "HEAD"])
        return self._with_mutex(_do)

    def run_pre_commit_hooks(self) -> dict:
        config_path = os.path.join(self._root, ".pre-commit-config.yaml")
        if not os.path.isfile(config_path):
            return {"success": True, "skipped": True, "message": "No .pre-commit-config.yaml found"}
        result = self._run(["pre-commit", "run", "--all-files"], timeout=120)
        return {
            "success": result["success"],
            "output": (result.get("stdout", "") + "\n" + result.get("stderr", "")).strip(),
        }

    def check_upstream(self, branch: str) -> dict:
        from ..version_manager import VersionManager
        vm = VersionManager(self._root)
        return vm.check_upstream_conflicts(branch)

    def validate_python(self, filepath: str) -> dict:
        abs_path = os.path.join(self._root, filepath)
        if not os.path.isfile(abs_path):
            return {"success": False, "error": f"File not found: {filepath}"}
        result = self._run(["python", "-m", "py_compile", abs_path])
        return {"success": result["success"], "file": filepath, "error": result.get("stderr", "")}

    def get_tool_definitions(self) -> list:
        return [
            {
                "name": "git_status",
                "description": "Show git status (changed, staged, untracked files).",
                "input_schema": {"type": "object", "properties": {}, "required": []}
            },
            {
                "name": "git_diff",
                "description": "Show git diff of current changes.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "cached": {"type": "boolean", "description": "Show staged changes only", "default": False}
                    },
                    "required": []
                }
            },
            {
                "name": "git_current_branch",
                "description": "Get the current git branch name.",
                "input_schema": {"type": "object", "properties": {}, "required": []}
            },
            {
                "name": "git_create_branch",
                "description": "Create and checkout a new git branch.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "branch_name": {"type": "string", "description": "Branch name to create"}
                    },
                    "required": ["branch_name"]
                }
            },
            {
                "name": "git_add",
                "description": "Stage specific files for commit. Only safe file types allowed. Never use git add -A.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "files": {"type": "array", "items": {"type": "string"}, "description": "List of file paths to stage"}
                    },
                    "required": ["files"]
                }
            },
            {
                "name": "git_commit",
                "description": "Commit staged changes with a message.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "Commit message"}
                    },
                    "required": ["message"]
                }
            },
            {
                "name": "git_push",
                "description": "Push current branch to remote.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "branch": {"type": "string", "description": "Branch to push (optional)"}
                    },
                    "required": []
                }
            },
            {
                "name": "validate_python",
                "description": "Validate Python syntax using py_compile.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "filepath": {"type": "string", "description": "Python file to validate"}
                    },
                    "required": ["filepath"]
                }
            },
            {
                "name": "git_create_tag",
                "description": "Create a git tag on HEAD.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "tag_name": {"type": "string", "description": "Tag name (e.g. v1.2.3)"},
                        "message": {"type": "string", "description": "Optional tag message"}
                    },
                    "required": ["tag_name"]
                }
            },
            {
                "name": "git_check_upstream",
                "description": "Check for upstream conflicts before pushing.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "branch": {"type": "string", "description": "Branch name to check"}
                    },
                    "required": ["branch"]
                }
            },
            {
                "name": "run_pre_commit",
                "description": "Run pre-commit hooks if configured.",
                "input_schema": {"type": "object", "properties": {}, "required": []}
            },
        ]

    def execute_tool(self, name: str, args: dict) -> dict:
        tools = {
            "git_status": lambda a: self.status(),
            "git_diff": lambda a: self.diff(cached=a.get("cached", False)),
            "git_current_branch": lambda a: self.current_branch(),
            "git_create_branch": lambda a: self.create_branch(a["branch_name"]),
            "git_add": lambda a: self.safe_add(a["files"]),
            "git_commit": lambda a: self.safe_commit(a["message"]),
            "git_push": lambda a: self.push(branch=a.get("branch")),
            "validate_python": lambda a: self.validate_python(a["filepath"]),
            "git_create_tag": lambda a: self.create_tag(a["tag_name"], a.get("message")),
            "git_check_upstream": lambda a: self.check_upstream(a["branch"]),
            "run_pre_commit": lambda a: self.run_pre_commit_hooks(),
        }
        fn = tools.get(name)
        if not fn:
            return {"success": False, "error": f"Unknown tool: {name}"}
        return fn(args)
