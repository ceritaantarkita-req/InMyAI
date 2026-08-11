from __future__ import annotations

import asyncio
import os

import uvicorn

from .main import app


def consume_lifecycle_shutdown_token() -> str:
    """Move the manager credential out of the inherited process environment."""
    return os.environ.pop('INMY_LIFECYCLE_SHUTDOWN_TOKEN', '')


def managed_port() -> int:
    raw = os.getenv('INMYAI_API_PORT', '8000')
    try:
        port = int(raw)
    except ValueError as error:
        raise RuntimeError('INMYAI_API_PORT must be an integer') from error
    if port < 1 or port > 65535:
        raise RuntimeError('INMYAI_API_PORT must be between 1 and 65535')
    return port


async def serve() -> None:
    config = uvicorn.Config(app, host='127.0.0.1', port=managed_port(), reload=False)
    server = uvicorn.Server(config)
    app.state.lifecycle_shutdown_token = consume_lifecycle_shutdown_token()
    app.state.lifecycle_shutdown_requested = False
    app.state.lifecycle_shutdown = lambda: setattr(server, 'should_exit', True)
    await server.serve()


def main() -> None:
    asyncio.run(serve())


if __name__ == '__main__':
    main()
