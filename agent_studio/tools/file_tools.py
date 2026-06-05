"""
File I/O tools for agents.
Enforces write allowlist and read blocklist to prevent prompt injection attacks.
"""
import os
import glob as globmod
from pathlib import Path
from typing import List, Optional
from ..config import AgentConfig


class FileTools:
    def __init__(self, repo_root: str = None):
        self._root = repo_root or AgentConfig.get_repo_root()

    def _is_safe_read(self, filepath: str) -> bool:
        rel = os.path.relpath(filepath, self._root).replace("\\", "/")
        for pattern in AgentConfig.BLOCKED_READ_PATTERNS:
            if pattern in rel:
                return False
        return True

    def _is_safe_write(self, filepath: str) -> bool:
        rel = os.path.relpath(filepath, self._root).replace("\\", "/")
        for safe_dir in AgentConfig.SAFE_WRITE_DIRS:
            if rel.startswith(safe_dir):
                ext = Path(filepath).suffix
                if ext in AgentConfig.SAFE_FILE_EXTENSIONS:
                    return True
        return False

    def read_file(self, filepath: str) -> dict:
        abs_path = self._resolve(filepath)
        if not abs_path:
            return {"success": False, "error": f"Path resolves outside repo: {filepath}"}
        if not self._is_safe_read(abs_path):
            return {"success": False, "error": f"Blocked: {filepath} matches read blocklist"}
        if not os.path.isfile(abs_path):
            return {"success": False, "error": f"File not found: {filepath}"}
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            if len(content) > 50000:
                content = content[:50000] + "\n... [truncated at 50000 chars]"
            return {"success": True, "content": content, "path": filepath}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def write_file(self, filepath: str, content: str) -> dict:
        abs_path = self._resolve(filepath)
        if not abs_path:
            return {"success": False, "error": f"Path resolves outside repo: {filepath}"}
        if not self._is_safe_write(abs_path):
            return {"success": False, "error": f"Blocked: {filepath} not in write allowlist (safe dirs: {AgentConfig.SAFE_WRITE_DIRS})"}
        try:
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            tmp_path = abs_path + ".agent_tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, abs_path)
            return {"success": True, "path": filepath, "bytes_written": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def edit_file(self, filepath: str, old_string: str, new_string: str) -> dict:
        result = self.read_file(filepath)
        if not result["success"]:
            return result
        content = result["content"]
        if old_string not in content:
            return {"success": False, "error": f"String to replace not found in {filepath}"}
        count = content.count(old_string)
        if count > 1:
            return {"success": False, "error": f"String appears {count} times — provide more context to make it unique"}
        new_content = content.replace(old_string, new_string, 1)
        return self.write_file(filepath, new_content)

    def glob_files(self, pattern: str) -> dict:
        full_pattern = os.path.join(self._root, pattern)
        matches = globmod.glob(full_pattern, recursive=True)
        safe_matches = [
            os.path.relpath(m, self._root).replace("\\", "/")
            for m in matches if self._is_safe_read(m)
        ]
        return {"success": True, "files": safe_matches[:100]}

    def grep(self, pattern: str, file_pattern: str = "**/*.py") -> dict:
        import re
        results = []
        glob_result = self.glob_files(file_pattern)
        for rel_path in glob_result.get("files", [])[:50]:
            abs_path = os.path.join(self._root, rel_path)
            try:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if re.search(pattern, line):
                            results.append({"file": rel_path, "line": i, "text": line.rstrip()[:200]})
                            if len(results) >= 50:
                                return {"success": True, "matches": results, "truncated": True}
            except Exception:
                continue
        return {"success": True, "matches": results, "truncated": False}

    def list_directory(self, dirpath: str = ".") -> dict:
        abs_path = self._resolve(dirpath)
        if not abs_path or not os.path.isdir(abs_path):
            return {"success": False, "error": f"Not a directory: {dirpath}"}
        try:
            entries = []
            for name in sorted(os.listdir(abs_path))[:100]:
                full = os.path.join(abs_path, name)
                entries.append({
                    "name": name,
                    "type": "dir" if os.path.isdir(full) else "file",
                    "size": os.path.getsize(full) if os.path.isfile(full) else 0,
                })
            return {"success": True, "entries": entries}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _resolve(self, filepath: str) -> Optional[str]:
        if os.path.isabs(filepath):
            abs_path = os.path.normpath(filepath)
        else:
            abs_path = os.path.normpath(os.path.join(self._root, filepath))
        if not abs_path.startswith(self._root):
            return None
        return abs_path

    def get_tool_definitions(self) -> list:
        return [
            {
                "name": "read_file",
                "description": "Read a file's content. Path is relative to repo root.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "filepath": {"type": "string", "description": "Relative file path"}
                    },
                    "required": ["filepath"]
                }
            },
            {
                "name": "write_file",
                "description": "Write content to a file. Only allowed in src/, gui_app/, tests/, docs/, scripts/.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "filepath": {"type": "string", "description": "Relative file path"},
                        "content": {"type": "string", "description": "Full file content"}
                    },
                    "required": ["filepath", "content"]
                }
            },
            {
                "name": "edit_file",
                "description": "Replace a unique string in a file. Fails if the string is not found or appears more than once.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "filepath": {"type": "string", "description": "Relative file path"},
                        "old_string": {"type": "string", "description": "Exact string to find"},
                        "new_string": {"type": "string", "description": "Replacement string"}
                    },
                    "required": ["filepath", "old_string", "new_string"]
                }
            },
            {
                "name": "glob_files",
                "description": "Find files matching a glob pattern (e.g. 'src/**/*.py').",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Glob pattern"}
                    },
                    "required": ["pattern"]
                }
            },
            {
                "name": "grep",
                "description": "Search for a regex pattern in files.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Regex pattern"},
                        "file_pattern": {"type": "string", "description": "Glob for files to search", "default": "**/*.py"}
                    },
                    "required": ["pattern"]
                }
            },
            {
                "name": "list_directory",
                "description": "List files and directories.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "dirpath": {"type": "string", "description": "Directory path relative to repo", "default": "."}
                    },
                    "required": []
                }
            },
        ]

    def execute_tool(self, name: str, args: dict) -> dict:
        tools = {
            "read_file": lambda a: self.read_file(a["filepath"]),
            "write_file": lambda a: self.write_file(a["filepath"], a["content"]),
            "edit_file": lambda a: self.edit_file(a["filepath"], a["old_string"], a["new_string"]),
            "glob_files": lambda a: self.glob_files(a["pattern"]),
            "grep": lambda a: self.grep(a["pattern"], a.get("file_pattern", "**/*.py")),
            "list_directory": lambda a: self.list_directory(a.get("dirpath", ".")),
        }
        fn = tools.get(name)
        if not fn:
            return {"success": False, "error": f"Unknown tool: {name}"}
        return fn(args)
