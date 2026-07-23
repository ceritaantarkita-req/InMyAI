"""Interactive terminal backed by a real PTY, exposed over a WebSocket.

Bridges a browser-side xterm.js terminal to a genuine, interactive local
shell process - PowerShell on Windows via `pywinpty` (wraps the Windows
ConPTY API), or bash/sh on POSIX via the stdlib `pty` module - so arrow
keys, tab completion, colors, and Ctrl+C all behave like a real terminal
instead of a plain subprocess pipe.

This is intentionally NOT sandboxed: whatever your OS user account can do,
a command typed here can do. That is an accepted tradeoff, the same as
opening any other terminal window on your own machine - InMyAI already runs
entirely locally under your own account with no multi-tenant boundary to
protect. It is reached over a local WebSocket (`/ws/terminal`), not exposed
publicly by anything in this app.

On Windows, this module requires `pywinpty` (see requirements.txt - it is
platform-gated so `pip install -r requirements.txt` does not fail on
Linux/Mac, where it simply is not installed and the POSIX `pty` path below
is used instead). If `pywinpty` is missing on Windows, PtySession.__init__
raises a clear RuntimeError that the WebSocket endpoint turns into an
error message the Terminal tab can display, rather than crashing the API.
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

IS_WINDOWS = platform.system() == 'Windows'

try:
    import winpty  # type: ignore
except ImportError:
    winpty = None  # type: ignore


class PtySession:
    """One interactive shell process behind a small, blocking-call
    interface. All methods here do blocking I/O and must only be invoked
    from a thread executor when called from async code (see
    run_terminal_session below) - never call them directly from the event
    loop thread.
    """

    def __init__(self, cwd: str, shell: Optional[str] = None, cols: int = 80, rows: int = 24):
        self.cwd = cwd
        self._posix_fd: int | None = None
        self._posix_pid: int | None = None
        self._winpty_proc = None

        if IS_WINDOWS:
            if winpty is None:
                raise RuntimeError(
                    "pywinpty is not installed. Run '.venv\\Scripts\\python.exe -m pip install "
                    "-r services\\api\\requirements.txt' and restart the API to enable the "
                    "Terminal tab on Windows."
                )
            command = shell or os.environ.get('COMSPEC') or 'powershell.exe'
            self._winpty_proc = winpty.PtyProcess.spawn(command, cwd=cwd, dimensions=(rows, cols))
        else:
            import pty
            shell_cmd = shell or os.environ.get('SHELL') or '/bin/bash'
            pid, fd = pty.fork()
            if pid == 0:
                try:
                    os.chdir(cwd)
                except OSError:
                    pass
                os.execvp(shell_cmd, [shell_cmd])
                os._exit(1)  # pragma: no cover - only reached if execvp fails
            self._posix_pid = pid
            self._posix_fd = fd

    def read(self, size: int = 4096) -> bytes:
        if self._winpty_proc is not None:
            try:
                data = self._winpty_proc.read(size)
            except EOFError:
                return b''
            return data.encode('utf-8', errors='replace') if isinstance(data, str) else data
        assert self._posix_fd is not None
        try:
            return os.read(self._posix_fd, size)
        except OSError:
            return b''

    def write(self, data: bytes) -> None:
        if self._winpty_proc is not None:
            self._winpty_proc.write(data.decode('utf-8', errors='replace'))
            return
        assert self._posix_fd is not None
        try:
            os.write(self._posix_fd, data)
        except OSError:
            pass

    def resize(self, cols: int, rows: int) -> None:
        if self._winpty_proc is not None:
            self._winpty_proc.setwinsize(rows, cols)
            return
        if self._posix_fd is None:
            return
        try:
            import fcntl
            import struct
            import termios
            fcntl.ioctl(self._posix_fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
        except (ImportError, OSError):
            pass

    def close(self) -> None:
        if self._winpty_proc is not None:
            try:
                self._winpty_proc.close()
            except Exception:
                pass
            return
        if self._posix_fd is not None:
            try:
                os.close(self._posix_fd)
            except OSError:
                pass
        if self._posix_pid is not None:
            try:
                os.kill(self._posix_pid, 15)
                os.waitpid(self._posix_pid, 0)
            except OSError:
                pass


async def run_terminal_session(websocket: WebSocket, cwd: str, shell: Optional[str] = None) -> None:
    """Own a WebSocket's full lifecycle for one terminal session: accept,
    spawn the PTY, relay bytes in both directions until either side hangs
    up, then clean up. Keystrokes and resize events arrive as JSON text
    frames (see the frontend's xterm.js glue); shell output is sent back as
    raw binary frames for xterm.js to write directly.
    """
    await websocket.accept()
    loop = asyncio.get_event_loop()
    try:
        session = await loop.run_in_executor(None, lambda: PtySession(cwd=cwd, shell=shell))
    except Exception as exc:
        await websocket.send_json({'type': 'error', 'message': str(exc)})
        await websocket.close()
        return

    async def pump_output() -> None:
        while True:
            data = await loop.run_in_executor(None, session.read)
            if not data:
                await websocket.send_json({'type': 'exit'})
                return
            await websocket.send_bytes(data)

    output_task = asyncio.create_task(pump_output())
    try:
        while True:
            message = await websocket.receive()
            if message.get('type') == 'websocket.disconnect':
                break
            text = message.get('text')
            raw = message.get('bytes')
            if raw is not None:
                await loop.run_in_executor(None, session.write, raw)
            elif text is not None:
                try:
                    payload = json.loads(text)
                except ValueError:
                    continue
                kind = payload.get('type')
                if kind == 'input':
                    await loop.run_in_executor(None, session.write, str(payload.get('data', '')).encode('utf-8'))
                elif kind == 'resize':
                    await loop.run_in_executor(None, session.resize, int(payload.get('cols', 80)), int(payload.get('rows', 24)))
    except WebSocketDisconnect:
        pass
    finally:
        # Close the PTY/kill the child process synchronously, on this
        # (event loop) thread, rather than via run_in_executor. session.close
        # only does fast, non-blocking syscalls (os.kill/os.close), so there
        # is nothing to gain from an executor thread here - and everything
        # to lose: pump_output's blocking os.read() is parked in a *separate*
        # executor thread from the shared default pool, cancelling its
        # asyncio Task does not interrupt that underlying blocking syscall.
        # Killing the child process is what actually unblocks it (the read
        # returns EOF once the pty slave goes away), letting that worker
        # thread return to the pool. Routing close() through the same
        # possibly-saturated pool instead risks it never getting scheduled.
        output_task.cancel()
        session.close()
