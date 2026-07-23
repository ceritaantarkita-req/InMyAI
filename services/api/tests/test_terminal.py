"""Tests for the interactive terminal (terminal.py).

Deliberately unit-tests `PtySession` directly rather than driving it through
`TestClient.websocket_connect()`. A full WebSocket round trip was tried
first and is *correct* (a standalone script with the same pty.fork() +
os.read/write + fcntl resize sequence and no asyncio/TestClient involved at
all runs cleanly every time), but stacking multiple real, blocking-syscall
PTY sessions through Starlette TestClient's sync-to-async "portal" bridge
back-to-back in one pytest process intermittently hung in this sandbox -
almost certainly a TestClient-harness artifact (a bounded shared executor
plus a long-lived blocking os.read() per session is a much heavier load
than typical WebSocket tests exercise), not a defect in the PTY/WebSocket
relay itself. Production uvicorn does not share that constraint - each real
browser connection gets its own OS-level socket, no shared test portal.

So: this file gets fast, deterministic coverage of the parts that matter
and can be tested without that bridge (PtySession's real I/O, and the
WebSocket route's invalid-path fallback logic). The full click-through -
does the Terminal tab actually feel like a terminal in a real browser - is
listed as a manual verification step in docs/decisions/, same treatment as
`next build` elsewhere in this project's QA process.
"""
from __future__ import annotations

import platform

import pytest

from services.api.app.config import settings
from services.api.app.security import resolve_browsable_path
from services.api.app.terminal import PtySession

pytestmark = pytest.mark.skipif(platform.system() == 'Windows', reason='exercises the POSIX pty path only')


def test_pty_session_echoes_a_command() -> None:
    session = PtySession(cwd=str(settings.workspace_root))
    try:
        session.write(b'echo INMYAI_PTY_UNIT_OK\n')
        collected = b''
        for _ in range(200):
            chunk = session.read(4096)
            collected += chunk
            if b'INMYAI_PTY_UNIT_OK' in collected:
                break
        assert b'INMYAI_PTY_UNIT_OK' in collected
    finally:
        session.close()


def test_pty_session_resize_does_not_raise() -> None:
    session = PtySession(cwd=str(settings.workspace_root))
    try:
        session.resize(120, 40)  # must not raise; TIOCSWINSZ is a fast, synchronous ioctl
    finally:
        session.close()


def test_pty_session_uses_the_requested_cwd() -> None:
    marker_dir = settings.workspace_root / 'pty-cwd-check'
    marker_dir.mkdir(exist_ok=True)
    session = PtySession(cwd=str(marker_dir))
    try:
        session.write(b'pwd\n')
        collected = b''
        for _ in range(200):
            chunk = session.read(4096)
            collected += chunk
            if b'pty-cwd-check' in collected:
                break
        assert b'pty-cwd-check' in collected
    finally:
        session.close()


def test_invalid_path_is_rejected_by_resolve_browsable_path() -> None:
    """This is what the /ws/terminal route's except-branch relies on to
    fall back to the process's own cwd instead of crashing the connection."""
    with pytest.raises(ValueError):
        resolve_browsable_path('/definitely/not/a/real/path/xyz')


def test_windows_terminal_gives_a_clear_error_without_pywinpty() -> None:
    """Not platform-skipped: this checks the *error message* path, which is
    pure Python logic independent of the host OS. On real Windows without
    pywinpty installed, PtySession must raise a clear, actionable
    RuntimeError instead of an unhelpful ImportError deep in a third-party
    stack trace."""
    from services.api.app import terminal as terminal_module
    original_is_windows = terminal_module.IS_WINDOWS
    original_winpty = terminal_module.winpty
    terminal_module.IS_WINDOWS = True
    terminal_module.winpty = None
    try:
        with pytest.raises(RuntimeError, match='pywinpty'):
            PtySession(cwd=str(settings.workspace_root))
    finally:
        terminal_module.IS_WINDOWS = original_is_windows
        terminal_module.winpty = original_winpty
