from __future__ import annotations

import ipaddress
import json
from urllib.parse import urlsplit


ALLOWED_HTTP_ORIGINS = frozenset({
    'http://127.0.0.1:3000',
    'http://localhost:3000',
    'http://tauri.localhost',
    'https://tauri.localhost',
    'tauri://localhost',
})


def _hostname_from_authority(authority: str | None) -> str | None:
    value = (authority or '').strip()
    if not value:
        return None
    try:
        return urlsplit(f'//{value}').hostname
    except ValueError:
        return None


def is_loopback_authority(authority: str | None) -> bool:
    hostname = _hostname_from_authority(authority)
    if not hostname:
        return False
    if hostname.lower() == 'localhost':
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def is_testclient_authority(scope: dict, authority: str | None) -> bool:
    client = scope.get('client') or ('', 0)
    client_host = str(client[0]).lower() if client else ''
    return client_host == 'testclient' and (authority or '').split(':', 1)[0].lower() == 'testserver'


class LocalAuthorityMiddleware:
    """Fail closed for browser/public authority before InMyAI HTTP routes.

    The product is local-first. Remote/mobile clients must later use the
    authenticated InMyHub gateway rather than reaching privileged product
    ports directly. TestClient's synthetic `testserver` authority is accepted
    only when Starlette identifies the synthetic client as `testclient`.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http':
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode('latin-1').lower(): value.decode('latin-1')
            for key, value in scope.get('headers', [])
        }
        host = headers.get('host')
        if not (is_loopback_authority(host) or is_testclient_authority(scope, host)):
            await self._reject(send, 'LOCAL_HOST_REQUIRED', 'Request Host must resolve to loopback InMyAI.')
            return

        origin = headers.get('origin')
        if origin and origin not in ALLOWED_HTTP_ORIGINS:
            await self._reject(send, 'LOCAL_ORIGIN_REQUIRED', 'Browser Origin is not authorized for local InMyAI.')
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send, code: str, message: str) -> None:
        body = json.dumps({'detail': message, 'code': code}, separators=(',', ':')).encode('utf-8')
        await send({
            'type': 'http.response.start',
            'status': 403,
            'headers': [
                (b'content-type', b'application/json; charset=utf-8'),
                (b'cache-control', b'no-store'),
                (b'x-content-type-options', b'nosniff'),
            ],
        })
        await send({'type': 'http.response.body', 'body': body})
