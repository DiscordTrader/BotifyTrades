"""
Version manager — SemVer bumping and upstream conflict detection.
"""
import os
import re
import subprocess
from typing import Optional, Tuple
from .config import AgentConfig


class VersionManager:
    def __init__(self, repo_root: str = None):
        self._root = repo_root or AgentConfig.get_repo_root()

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

    # ── SemVer ──

    def get_latest_version(self) -> str:
        result = self._run_git(["git", "tag", "--sort=-v:refname", "-l", "v*"])
        if result["success"] and result["stdout"]:
            first_tag = result["stdout"].split("\n")[0].strip()
            if re.match(r'^v?\d+\.\d+\.\d+', first_tag):
                return first_tag.lstrip("v")
        return "0.0.0"

    def parse_version(self, version: str) -> Tuple[int, int, int]:
        match = re.match(r'(\d+)\.(\d+)\.(\d+)', version)
        if not match:
            return (0, 0, 0)
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))

    def bump_version(self, commit_message: str) -> dict:
        current = self.get_latest_version()
        major, minor, patch = self.parse_version(current)

        msg_lower = commit_message.lower()
        if msg_lower.startswith("feat:") or msg_lower.startswith("feat("):
            minor += 1
            patch = 0
            bump_type = "minor"
        elif msg_lower.startswith("fix:") or msg_lower.startswith("fix("):
            patch += 1
            bump_type = "patch"
        elif "breaking" in msg_lower or "BREAKING" in commit_message:
            major += 1
            minor = 0
            patch = 0
            bump_type = "major"
        else:
            patch += 1
            bump_type = "patch"

        new_version = f"{major}.{minor}.{patch}"
        return {
            "previous": current,
            "new": new_version,
            "bump_type": bump_type,
            "tag": f"v{new_version}",
        }

    def create_version_tag(self, version_info: dict) -> dict:
        tag = version_info["tag"]
        result = self._run_git(["git", "tag", "-a", tag, "-m", f"Release {tag}"])
        if not result["success"]:
            result_light = self._run_git(["git", "tag", tag])
            if not result_light["success"]:
                return {"success": False, "error": f"Failed to create tag: {result_light['stderr']}"}
        return {"success": True, "tag": tag, "version": version_info["new"]}

    # ── Conflict Detection ──

    def check_upstream_conflicts(self, branch: str) -> dict:
        fetch = self._run_git(["git", "fetch", "origin", "--no-tags"], timeout=30)
        if not fetch["success"]:
            return {
                "has_conflicts": False,
                "checked": False,
                "reason": f"Could not fetch origin: {fetch['stderr']}",
            }

        remote_ref = f"origin/{branch}"
        remote_exists = self._run_git(["git", "rev-parse", "--verify", remote_ref])

        if not remote_exists["success"]:
            return {"has_conflicts": False, "checked": True, "reason": "New branch, no upstream"}

        merge_base = self._run_git(["git", "merge-base", "HEAD", remote_ref])
        if not merge_base["success"]:
            return {"has_conflicts": False, "checked": False, "reason": "Could not find merge base"}

        remote_head = self._run_git(["git", "rev-parse", remote_ref])
        if remote_head["success"] and remote_head["stdout"] == merge_base["stdout"]:
            return {"has_conflicts": False, "checked": True, "reason": "Up to date with remote"}

        diff_check = self._run_git(["git", "diff", "--name-only", f"{merge_base['stdout']}..{remote_ref}"])
        if not diff_check["success"]:
            return {"has_conflicts": False, "checked": False, "reason": "Could not diff against remote"}

        remote_changed = set(diff_check["stdout"].split("\n")) if diff_check["stdout"] else set()

        local_diff = self._run_git(["git", "diff", "--name-only", f"{merge_base['stdout']}..HEAD"])
        local_changed = set(local_diff["stdout"].split("\n")) if local_diff["success"] and local_diff["stdout"] else set()

        overlapping = remote_changed & local_changed
        if overlapping:
            return {
                "has_conflicts": True,
                "checked": True,
                "conflicting_files": list(overlapping),
                "reason": f"{len(overlapping)} file(s) changed both locally and on remote",
            }

        return {
            "has_conflicts": False,
            "checked": True,
            "reason": "Remote has new commits but no overlapping file changes",
            "remote_changed_files": list(remote_changed)[:20],
        }
