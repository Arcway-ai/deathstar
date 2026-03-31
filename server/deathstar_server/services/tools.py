from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

from deathstar_server.providers.base import ToolCall, ToolDefinition, ToolResult

logger = logging.getLogger(__name__)

# Maximum sizes for safety
_MAX_FILE_SIZE = 50_000  # chars
_MAX_COMMAND_OUTPUT = 10_000  # chars
_COMMAND_TIMEOUT = 30  # seconds


def workspace_tools() -> list[ToolDefinition]:
    """Return tool definitions for workspace operations."""
    return [
        ToolDefinition(
            name="read_file",
            description="Read the contents of a file in the workspace. Returns the file content as text.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repo-relative file path (e.g. 'src/main.py')",
                    },
                },
                "required": ["path"],
            },
        ),
        ToolDefinition(
            name="write_file",
            description="Write content to a file in the workspace. Creates the file if it doesn't exist, overwrites if it does.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repo-relative file path",
                    },
                    "content": {
                        "type": "string",
                        "description": "The full file content to write",
                    },
                },
                "required": ["path", "content"],
            },
        ),
        ToolDefinition(
            name="list_files",
            description="List files in a directory. Returns file paths relative to the given directory.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repo-relative directory path. Use '.' for repo root.",
                        "default": ".",
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Optional glob pattern to filter files (e.g. '*.py', '**/*.ts')",
                    },
                },
                "required": [],
            },
        ),
        ToolDefinition(
            name="search_files",
            description="Search for a pattern in files using grep. Returns matching lines with file paths and line numbers.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Search pattern (regex supported)",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in (repo-relative). Defaults to repo root.",
                        "default": ".",
                    },
                    "file_pattern": {
                        "type": "string",
                        "description": "Glob to filter which files to search (e.g. '*.py')",
                    },
                },
                "required": ["pattern"],
            },
        ),
        ToolDefinition(
            name="run_command",
            description="Run a shell command in the workspace. Use for git commands, tests, linting, etc. Commands run in the repo root directory.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to run (e.g. 'git status', 'python -m pytest tests/')",
                    },
                },
                "required": ["command"],
            },
        ),
        ToolDefinition(
            name="git_diff",
            description="Show the current git diff (staged and unstaged changes).",
            parameters={
                "type": "object",
                "properties": {
                    "staged_only": {
                        "type": "boolean",
                        "description": "If true, show only staged changes",
                        "default": False,
                    },
                },
                "required": [],
            },
        ),
        ToolDefinition(
            name="git_log",
            description="Show recent git commit history.",
            parameters={
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "description": "Number of commits to show",
                        "default": 10,
                    },
                },
                "required": [],
            },
        ),
    ]


class ToolExecutor:
    """Executes workspace tools against a repo directory."""

    def __init__(self, repo_root: Path, *, allow_writes: bool = False) -> None:
        self.repo_root = repo_root.resolve()
        self.allow_writes = allow_writes

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call and return the result."""
        try:
            handler = _TOOL_HANDLERS.get(tool_call.name)
            if not handler:
                return ToolResult(
                    tool_call_id=tool_call.id,
                    content=f"Unknown tool: {tool_call.name}",
                    is_error=True,
                )
            content = handler(self, tool_call.arguments)
            return ToolResult(tool_call_id=tool_call.id, content=content)
        except PermissionError as exc:
            return ToolResult(tool_call_id=tool_call.id, content=str(exc), is_error=True)
        except Exception as exc:
            logger.warning("tool %s failed: %s", tool_call.name, exc)
            return ToolResult(
                tool_call_id=tool_call.id,
                content=f"Error executing {tool_call.name}: {exc}",
                is_error=True,
            )

    def _resolve_path(self, rel_path: str) -> Path:
        """Resolve a repo-relative path, rejecting traversals."""
        full = (self.repo_root / rel_path).resolve()
        if not full.is_relative_to(self.repo_root):
            raise PermissionError(f"Path escapes repo root: {rel_path}")
        return full

    def _read_file(self, args: dict[str, Any]) -> str:
        path = self._resolve_path(args["path"])
        if not path.is_file():
            return f"File not found: {args['path']}"
        content = path.read_text(encoding="utf-8", errors="replace")
        if len(content) > _MAX_FILE_SIZE:
            content = content[:_MAX_FILE_SIZE] + "\n...[truncated]"
        return content

    def _write_file(self, args: dict[str, Any]) -> str:
        if not self.allow_writes:
            raise PermissionError("Write operations are disabled. Enable 'Apply changes' to allow writes.")
        path = self._resolve_path(args["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"], encoding="utf-8")
        return f"Written {len(args['content'])} chars to {args['path']}"

    def _list_files(self, args: dict[str, Any]) -> str:
        dir_path = self._resolve_path(args.get("path", "."))
        if not dir_path.is_dir():
            return f"Not a directory: {args.get('path', '.')}"

        pattern = args.get("pattern", "*")
        files = sorted(dir_path.rglob(pattern) if "**" in pattern else dir_path.glob(pattern))
        # Filter out hidden/ignored dirs
        ignored = {".git", "node_modules", "__pycache__", ".venv", "dist", "build"}
        results: list[str] = []
        for f in files[:200]:
            parts = f.relative_to(self.repo_root).parts
            if any(p in ignored for p in parts):
                continue
            results.append(str(f.relative_to(self.repo_root)))
        return "\n".join(results) if results else "(no files found)"

    def _search_files(self, args: dict[str, Any]) -> str:
        search_path = self._resolve_path(args.get("path", "."))
        cmd = ["grep", "-rn", "--include", args.get("file_pattern", "*"), args["pattern"], str(search_path)]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=_COMMAND_TIMEOUT,
            )
            output = result.stdout.strip()
            # Make paths relative to repo root
            output = output.replace(str(self.repo_root) + "/", "")
            if len(output) > _MAX_COMMAND_OUTPUT:
                output = output[:_MAX_COMMAND_OUTPUT] + "\n...[truncated]"
            return output if output else "(no matches)"
        except subprocess.TimeoutExpired:
            return "Search timed out"
        except Exception as exc:
            return f"Search failed: {exc}"

    def _run_command(self, args: dict[str, Any]) -> str:
        command = args["command"]
        # Safety: block dangerous commands
        dangerous = ["rm -rf /", "mkfs", "dd if=", "> /dev/sd", "chmod -R 777 /"]
        for d in dangerous:
            if d in command:
                raise PermissionError(f"Blocked dangerous command pattern: {d}")

        try:
            result = subprocess.run(
                command, shell=True, cwd=str(self.repo_root),
                capture_output=True, text=True, timeout=_COMMAND_TIMEOUT,
            )
            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                output += ("\n" if output else "") + result.stderr
            if result.returncode != 0:
                output += f"\n(exit code: {result.returncode})"
            output = output.strip()
            if len(output) > _MAX_COMMAND_OUTPUT:
                output = output[:_MAX_COMMAND_OUTPUT] + "\n...[truncated]"
            return output if output else "(no output)"
        except subprocess.TimeoutExpired:
            return f"Command timed out after {_COMMAND_TIMEOUT}s"

    def _git_diff(self, args: dict[str, Any]) -> str:
        staged_only = args.get("staged_only", False)
        cmd = ["git", "diff"]
        if staged_only:
            cmd.append("--cached")
        cmd.extend(["--stat", "--patch"])
        try:
            result = subprocess.run(
                cmd, cwd=str(self.repo_root),
                capture_output=True, text=True, timeout=_COMMAND_TIMEOUT,
            )
            output = result.stdout.strip()
            if len(output) > _MAX_COMMAND_OUTPUT:
                output = output[:_MAX_COMMAND_OUTPUT] + "\n...[truncated]"
            return output if output else "(no changes)"
        except Exception as exc:
            return f"git diff failed: {exc}"

    def _git_log(self, args: dict[str, Any]) -> str:
        count = min(args.get("count", 10), 50)
        try:
            result = subprocess.run(
                ["git", "log", f"-{count}", "--oneline", "--graph"],
                cwd=str(self.repo_root),
                capture_output=True, text=True, timeout=_COMMAND_TIMEOUT,
            )
            return result.stdout.strip() or "(no commits)"
        except Exception as exc:
            return f"git log failed: {exc}"


# Map tool names to handler methods
_TOOL_HANDLERS: dict[str, Any] = {
    "read_file": ToolExecutor._read_file,
    "write_file": ToolExecutor._write_file,
    "list_files": ToolExecutor._list_files,
    "search_files": ToolExecutor._search_files,
    "run_command": ToolExecutor._run_command,
    "git_diff": ToolExecutor._git_diff,
    "git_log": ToolExecutor._git_log,
}
