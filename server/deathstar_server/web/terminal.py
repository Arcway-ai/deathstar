"""WebSocket terminal — spawns a PTY shell and relays I/O."""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import pty
import struct
import termios

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from deathstar_server.app_state import settings

logger = logging.getLogger(__name__)

terminal_router = APIRouter(prefix="/web/api")

# Max concurrent terminal sessions per server
_MAX_SESSIONS = 4
_active_sessions: set[str] = set()


def _authenticate(websocket: WebSocket) -> bool:
    """Check session cookie or token. When no API token is configured, allow all."""
    if not settings.api_token:
        return True  # No auth configured — allow (matches HTTP middleware behavior)
    from deathstar_server.session import SESSION_COOKIE_NAME, validate_session_token
    cookie = websocket.cookies.get(SESSION_COOKIE_NAME)
    if cookie and validate_session_token(cookie, settings.api_token):
        return True
    # Fallback: check query param token for backward compatibility
    token = websocket.query_params.get("token")
    if token:
        import hmac
        return hmac.compare_digest(token, settings.api_token)
    return False


@terminal_router.websocket("/terminal")
async def terminal_ws(
    websocket: WebSocket,
    repo: str | None = Query(default=None),
):
    """WebSocket terminal endpoint.

    Query params:
      - repo: optional repo name to cd into on start
    """
    logger.info("terminal WS connection attempt from %s (repo=%s)", websocket.client, repo)

    if not _authenticate(websocket):
        logger.warning("terminal auth failed for %s", websocket.client)
        await websocket.close(code=4001, reason="unauthorized")
        return

    if len(_active_sessions) >= _MAX_SESSIONS:
        logger.warning("terminal session limit reached (%d/%d)", len(_active_sessions), _MAX_SESSIONS)
        await websocket.close(code=4002, reason="too many terminal sessions")
        return

    await websocket.accept()
    logger.info("terminal WS accepted for %s", websocket.client)

    session_id = f"term-{id(websocket)}"
    _active_sessions.add(session_id)

    # Determine starting directory — validate repo against path traversal
    cwd = str(settings.workspace_root / "projects")
    if repo:
        if ".." in repo or repo.startswith("/"):
            await websocket.close(code=4003, reason="invalid repo name")
            return
        repo_path = (settings.workspace_root / "projects" / repo).resolve()
        projects_root = (settings.workspace_root / "projects").resolve()
        if not repo_path.is_relative_to(projects_root):
            await websocket.close(code=4003, reason="invalid repo name")
            return
        if repo_path.is_dir():
            cwd = str(repo_path)

    # Spawn PTY + shell
    logger.info("terminal %s: spawning PTY in %s", session_id, cwd)
    master_fd, slave_fd = pty.openpty()

    # Set initial terminal size (80x24)
    _set_winsize(master_fd, 24, 80)

    env = {
        **os.environ,
        "TERM": "xterm-256color",
        "COLORTERM": "truecolor",
        "HOME": os.environ.get("HOME", "/home/deathstar"),
        "LANG": "en_US.UTF-8",
    }

    pid = os.fork()
    if pid == 0:
        # Child process — become session leader and exec shell
        os.setsid()
        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)
        os.close(master_fd)
        os.close(slave_fd)
        os.chdir(cwd)
        # Prefer zsh, fall back to bash
        shell = "/usr/bin/zsh" if os.path.exists("/usr/bin/zsh") else "/bin/bash"
        os.execve(shell, [shell, "--login"], env)
        # Never reached

    # Parent
    os.close(slave_fd)

    # Make master_fd non-blocking
    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    loop = asyncio.get_event_loop()

    try:
        # Task: read from PTY → send to WebSocket
        async def pty_to_ws():
            while True:
                try:
                    data = await loop.run_in_executor(
                        None, _blocking_read, master_fd, pid
                    )
                    if data is None:
                        break  # EOF — child exited
                    if data:
                        await websocket.send_bytes(data)
                except OSError:
                    break
                except WebSocketDisconnect:
                    break

        # Task: read from WebSocket → write to PTY
        async def ws_to_pty():
            while True:
                try:
                    message = await websocket.receive()
                except WebSocketDisconnect:
                    break

                if message.get("type") == "websocket.disconnect":
                    break

                if "bytes" in message:
                    data = message["bytes"]
                    os.write(master_fd, data)
                elif "text" in message:
                    text = message["text"]
                    # Check for resize messages (JSON)
                    if text.startswith("{"):
                        try:
                            msg = json.loads(text)
                            if msg.get("type") == "resize":
                                rows = msg.get("rows", 24)
                                cols = msg.get("cols", 80)
                                _set_winsize(master_fd, rows, cols)
                                continue
                        except (json.JSONDecodeError, KeyError):
                            pass
                    os.write(master_fd, text.encode("utf-8"))

        # Run both tasks concurrently
        done, pending = await asyncio.wait(
            [asyncio.create_task(pty_to_ws()), asyncio.create_task(ws_to_pty())],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()

    except Exception:
        logger.exception("terminal session %s error", session_id)
    finally:
        logger.info("terminal session %s closing (pid=%d)", session_id, pid)
        _active_sessions.discard(session_id)
        os.close(master_fd)
        # Clean up child process
        try:
            os.kill(pid, 9)
            os.waitpid(pid, 0)
        except OSError:
            pass
        try:
            await websocket.close()
        except Exception:
            pass


def _blocking_read(fd: int, child_pid: int) -> bytes | None:
    """Read from PTY fd, blocking.

    Returns:
      bytes — data read from the PTY
      None  — child process has exited (EOF)
    """
    import select

    r, _, _ = select.select([fd], [], [], 0.5)
    if fd in r:
        try:
            data = os.read(fd, 4096)
            if not data:
                return None  # EOF
            return data
        except OSError:
            return None  # PTY closed
    # Timeout — check if the child is still alive
    try:
        pid_result, _ = os.waitpid(child_pid, os.WNOHANG)
        if pid_result != 0:
            return None  # child exited
    except ChildProcessError:
        return None
    return b""  # no data yet, keep waiting


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    """Set the terminal window size on a PTY file descriptor."""
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
