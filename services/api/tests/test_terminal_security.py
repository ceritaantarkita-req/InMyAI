"""Security regression tests for the real-shell WebSocket boundary.

The Terminal is intentionally not sandboxed, so its browser handshake is a
privilege boundary: a public web page must never be able to connect to the
local PTY merely because the API listens on localhost. These tests stay
platform-independent and do not spawn a PTY.
"""
from __future__ import annotations

import asyncio

from services.api.app import terminal as terminal_module


class FakeWebSocket:
    def __init__(self, origin: str | None):
        self.headers = {} if origin is None else {'origin': origin}
        self.closed: tuple[int, str] | None = None

    async def close(self, code: int = 1000, reason: str = '') -> None:
        self.closed = (code, reason)


def test_terminal_origin_allows_supported_inmyai_clients() -> None:
    assert terminal_module.is_terminal_origin_allowed('http://127.0.0.1:3000')
    assert terminal_module.is_terminal_origin_allowed('http://localhost:3000')
    assert terminal_module.is_terminal_origin_allowed('http://tauri.localhost')
    assert terminal_module.is_terminal_origin_allowed('https://tauri.localhost')
    assert terminal_module.is_terminal_origin_allowed('tauri://localhost')


def test_terminal_origin_rejects_cross_site_lan_and_lookalikes() -> None:
    assert not terminal_module.is_terminal_origin_allowed(None)
    assert not terminal_module.is_terminal_origin_allowed('')
    assert not terminal_module.is_terminal_origin_allowed('https://evil.example')
    assert not terminal_module.is_terminal_origin_allowed('http://localhost:3000.evil.example')
    assert not terminal_module.is_terminal_origin_allowed('http://192.168.1.25.evil.example:3000')
    assert not terminal_module.is_terminal_origin_allowed('http://192.168.1.25:3000')
    assert not terminal_module.is_terminal_origin_allowed('http://10.12.3.4:3000')
    assert not terminal_module.is_terminal_origin_allowed('http://172.31.5.9:3000')
    assert not terminal_module.is_terminal_origin_allowed('http://127.0.0.1:3001')
    assert not terminal_module.is_terminal_origin_allowed('null')


def test_untrusted_origin_is_closed_with_policy_violation() -> None:
    websocket = FakeWebSocket('https://evil.example')
    allowed = asyncio.run(terminal_module.authorize_terminal_websocket(websocket))

    assert allowed is False
    assert websocket.closed == (1008, 'Untrusted terminal WebSocket origin.')


def test_trusted_origin_passes_without_closing() -> None:
    websocket = FakeWebSocket('http://127.0.0.1:3000')
    allowed = asyncio.run(terminal_module.authorize_terminal_websocket(websocket))

    assert allowed is True
    assert websocket.closed is None


def test_run_terminal_session_rejects_before_spawning_pty(monkeypatch) -> None:
    spawned = False

    class MustNotSpawnPty:
        def __init__(self, *args, **kwargs):
            nonlocal spawned
            spawned = True
            raise AssertionError('PTY must not spawn for an untrusted browser origin')

    monkeypatch.setattr(terminal_module, 'PtySession', MustNotSpawnPty)
    websocket = FakeWebSocket('https://attacker.example')

    asyncio.run(terminal_module.run_terminal_session(websocket, cwd='.'))

    assert spawned is False
    assert websocket.closed is not None
    assert websocket.closed[0] == 1008
