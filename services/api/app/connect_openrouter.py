from __future__ import annotations

import ipaddress
import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx


_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_CONNECTION_ID = re.compile(r'^conn_[A-Za-z0-9_-]{16,96}$')
_MODEL_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/~-]{0,191}$')
_IDEMPOTENCY_KEY = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/-]{7,255}$')


class ConnectOpenRouterError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 503, code: str = 'CONNECT_OPENROUTER_ERROR') -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _bounded_string(value: Any, label: str, *, minimum: int = 1, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum or '\x00' in value:
        raise ValueError(f'{label} must be a bounded NUL-free string.')
    if value.strip() != value:
        raise ValueError(f'{label} cannot have surrounding whitespace.')
    return value


def _normalize_loopback_base_url(value: str) -> str:
    raw = _bounded_string(value, 'connect_base_url', minimum=8, maximum=256)
    parsed = urlparse(raw)
    if parsed.scheme != 'http':
        raise ValueError('InMyConnect base URL must use plain HTTP on loopback.')
    if parsed.username or parsed.password:
        raise ValueError('InMyConnect base URL cannot contain credentials.')
    if parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError('InMyConnect base URL cannot contain path, query, or fragment data.')
    if parsed.port is None:
        raise ValueError('InMyConnect base URL must include an explicit port.')
    try:
        address = ipaddress.ip_address(parsed.hostname or '')
    except ValueError as exc:
        raise ValueError('InMyConnect base URL must use an explicit loopback IP literal.') from exc
    if not address.is_loopback:
        raise ValueError('InMyConnect base URL must be loopback-only.')
    host = f'[{address.compressed}]' if address.version == 6 else address.compressed
    return f'http://{host}:{parsed.port}'


def _normalize_bearer_token(value: str) -> str:
    token = _bounded_string(value, 'Hub service token', minimum=16, maximum=8192)
    if re.search(r'\s', token):
        raise ValueError('Hub service token is malformed.')
    return token


def _validate_connection_id(value: str) -> str:
    candidate = _bounded_string(value, 'connection_id', maximum=101)
    if not _CONNECTION_ID.fullmatch(candidate):
        raise ValueError('connection_id is invalid.')
    return candidate


def _validate_model_id(value: str) -> str:
    candidate = _bounded_string(value, 'model_id', maximum=192)
    if not _MODEL_ID.fullmatch(candidate):
        raise ValueError('model_id is invalid.')
    return candidate


def _validate_idempotency_key(value: str) -> str:
    candidate = _bounded_string(value, 'idempotency_key', minimum=8, maximum=256)
    if not _IDEMPOTENCY_KEY.fullmatch(candidate):
        raise ValueError('idempotency_key is invalid.')
    return candidate


class ConnectOpenRouterClient:
    """Server-side client for the local InMyConnect OpenRouter bridge.

    This object never talks to OpenRouter directly. The Bearer credential is
    the InMyHub service identity for agent:inmyai and is only forwarded to the
    local Connect boundary. The OpenRouter API key remains inside InMyConnect.
    """

    def __init__(
        self,
        *,
        base_url: str,
        hub_service_token: str,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = _normalize_loopback_base_url(base_url)
        self._token = _normalize_bearer_token(hub_service_token)
        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or not 1 <= float(timeout_seconds) <= 60:
            raise ValueError('connect timeout must be between 1 and 60 seconds.')
        self.timeout_seconds = float(timeout_seconds)
        self.transport = transport

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if method not in {'GET', 'POST'} or not path.startswith('/api/openrouter/'):
            raise ValueError('InMyConnect OpenRouter request shape is invalid.')
        headers = {
            'accept': 'application/json',
            'authorization': f'Bearer {self._token}',
        }
        if method == 'POST':
            headers['content-type'] = 'application/json'

        timeout = httpx.Timeout(self.timeout_seconds)
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            try:
                async with client.stream(
                    method,
                    f'{self.base_url}{path}',
                    headers=headers,
                    json=payload if method == 'POST' else None,
                ) as response:
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > _MAX_RESPONSE_BYTES:
                            raise ConnectOpenRouterError('InMyConnect response exceeded the bounded response size.')
                    try:
                        decoded = json.loads(body.decode('utf-8')) if body else {}
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise ConnectOpenRouterError('InMyConnect returned invalid JSON.') from exc
                    if not isinstance(decoded, dict):
                        raise ConnectOpenRouterError('InMyConnect response must be a JSON object.')
                    if response.status_code < 200 or response.status_code >= 300:
                        code = decoded.get('code') if isinstance(decoded.get('code'), str) else 'CONNECT_HTTP_ERROR'
                        safe_code = code if re.fullmatch(r'[A-Z0-9_:-]{2,128}', code) else 'CONNECT_HTTP_ERROR'
                        raise ConnectOpenRouterError(
                            f'InMyConnect request failed with status {response.status_code} ({safe_code}).',
                            status_code=response.status_code,
                            code=safe_code,
                        )
                    return decoded
            except ConnectOpenRouterError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                raise ConnectOpenRouterError('InMyConnect local runtime is unavailable.') from exc

    async def status(self) -> dict[str, Any]:
        return await self._request('GET', '/api/openrouter/status')

    async def list_models(self, *, connection_id: str, idempotency_key: str) -> dict[str, Any]:
        return await self._request('POST', '/api/openrouter/models', {
            'connectionId': _validate_connection_id(connection_id),
            'idempotencyKey': _validate_idempotency_key(idempotency_key),
        })

    async def chat(
        self,
        *,
        workflow_run_id: str,
        delegation_id: str,
        connection_id: str,
        model_id: str,
        idempotency_key: str,
        input_sensitivity: str,
        requested_output_tokens: int,
        messages: list[dict[str, str]],
    ) -> dict[str, Any]:
        workflow = _bounded_string(workflow_run_id, 'workflow_run_id', minimum=3, maximum=128)
        delegation = _bounded_string(delegation_id, 'delegation_id', minimum=3, maximum=128)
        connection = _validate_connection_id(connection_id)
        model = _validate_model_id(model_id)
        idem = _validate_idempotency_key(idempotency_key)
        if input_sensitivity not in {'PUBLIC', 'INTERNAL'}:
            raise ValueError('input_sensitivity must be PUBLIC or INTERNAL.')
        if isinstance(requested_output_tokens, bool) or not isinstance(requested_output_tokens, int) or not 1 <= requested_output_tokens <= 8192:
            raise ValueError('requested_output_tokens must be between 1 and 8192.')
        if not isinstance(messages, list) or not 1 <= len(messages) <= 128:
            raise ValueError('messages must contain 1..128 items.')
        normalized_messages: list[dict[str, str]] = []
        total_chars = 0
        for index, message in enumerate(messages):
            if not isinstance(message, dict) or set(message) != {'role', 'content'}:
                raise ValueError(f'messages[{index}] must contain exactly role and content.')
            role = message.get('role')
            content = message.get('content')
            if role not in {'system', 'user', 'assistant'}:
                raise ValueError(f'messages[{index}].role is unsupported.')
            text = _bounded_string(content, f'messages[{index}].content', maximum=131072)
            total_chars += len(text)
            if total_chars > 131072:
                raise ValueError('messages total content exceeds 131072 characters.')
            normalized_messages.append({'role': role, 'content': text})

        return await self._request('POST', '/api/openrouter/chat', {
            'workflowRunId': workflow,
            'delegationId': delegation,
            'connectionId': connection,
            'modelId': model,
            'idempotencyKey': idem,
            'inputSensitivity': input_sensitivity,
            'requestedOutputTokens': requested_output_tokens,
            'inputs': {'messages': normalized_messages},
        })


def create_connect_openrouter_client(*, base_url: str, hub_service_token: str, timeout_seconds: float = 20.0) -> ConnectOpenRouterClient:
    return ConnectOpenRouterClient(
        base_url=base_url,
        hub_service_token=hub_service_token,
        timeout_seconds=timeout_seconds,
    )
