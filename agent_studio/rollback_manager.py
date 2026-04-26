"""
Rollback manager — safely reverts agent-created commits.
Tracks commit SHAs per task and provides one-click undo.
"""
import os
import subprocess
from typing import Optional
from .config import AgentConfig


class RollbackManager:
    def __init__(self, repo_root: str = None):
        self._root = repo_root or AgentConfig.get_repo_root()
        self._mutex_dir = os.path.join(self._root, ".git", "autosave_mutex")

    def _run_git(self, cmd: list, timeout: int = 30) -> dict:
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
            }
        except Exception as e:
            return {"success": False, "stdout": "", "stderr": str(e)}

    def _acquire_mutex(self) -> bool:
        import time
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

    def rollback_commit(self, commit_sha: str, branch: str) -> dict:
        if not self._acquire_mutex():
            return {"success": False, "error": "Could not acquire git mutex"}
        try:
            return self._do_rollback(commit_sha, branch)
        finally:
            self._release_mutex()

    def _do_rollback(self, commit_sha: str, branch: str) -> dict:
        current = self._run_git(["git", "branch", "--show-current"])
        if not current["success"]:
            return {"success": False, "error": "Could not determine current branch"}

        original_branch = current["stdout"]
        on_target = original_branch == branch

        if not on_target:
            checkout = self._run_git(["git", "checkout", branch])
            if not checkout["success"]:
                return {"success": False, "error": f"Could not checkout {branch}: {checkout['stderr']}"}

        verify = self._run_git(["git", "log", "--oneline", "-1", commit_sha])
        if not verify["success"]:
            if not on_target:
                self._run_git(["git", "checkout", original_branch])
            return {"success": False, "error": f"Commit {commit_sha} not found"}

        head = self._run_git(["git", "rev-parse", "HEAD"])
        if head["success"] and head["stdout"] == commit_sha:
            revert = self._run_git(["git", "revert", "--no-edit", commit_sha])
            if not revert["success"]:
                return {"success": False, "error": f"Revert failed: {revert['stderr']}"}

            new_head = self._run_git(["git", "rev-parse", "HEAD"])
            return {
                "success": True,
                "method": "revert",
                "original_commit": commit_sha,
                "revert_commit": new_head.get("stdout", ""),
                "branch": branch,
            }

        revert = self._run_git(["git", "revert", "--no-edit", commit_sha])
        if not revert["success"]:
            if not on_target:
                self._run_git(["git", "checkout", original_branch])
            return {"success": False, "error": f"Revert failed: {revert['stderr']}"}

        new_head = self._run_git(["git", "rev-parse", "HEAD"])
        if not on_target:
            self._run_git(["git", "checkout", original_branch])

        return {
            "success": True,
            "method": "revert",
            "original_commit": commit_sha,
            "revert_commit": new_head.get("stdout", ""),
            "branch": branch,
        }

    def get_commit_info(self, commit_sha: str) -> Optional[dict]:
        result = self._run_git(["git", "log", "--format=%H|%s|%an|%ai", "-1", commit_sha])
        if not result["success"]:
            return None
        parts = result["stdout"].split("|", 3)
        if len(parts) < 4:
            return None
        return {
            "sha": parts[0],
            "message": parts[1],
            "author": parts[2],
            "date": parts[3],
        }
