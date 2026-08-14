from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from services.api.app.connect_openrouter import ConnectOpenRouterClient, ConnectOpenRouterError


TOKEN = 'hub-service-test-token-0123456789'
CONNECTION_ID = 'conn_' + ('a' * 16)


def make_client(handler, *, base_url: str = 'http://127.0.0.1:8766') -> ConnectOpenRouterClient:
    return ConnectOpenRouterClient(
        base_url=base_url,
        hub_service_token=TOKEN,
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )


def test_connect_client_accepts_only_explicit_loopback_http_origins() -> None:
    handler = lambda request: httpx.Response(200, json={'ok': True})
    assert make_client(handler).base_url == 'http://127.0.0.1:8766'
    assert make_client(handler, base_url='http://[::1]:8766').base_url == 'http://[::1]:8766'
    for invalid in (
        'http://localhost:8766',
        'http://192.168.1.20:8766',
        'https://127.0.0.1:8766',
        'http://127.0.0.1',
        'http://user:pass@127.0.0.1:8766',
        'http://127.0.0.1:8766/api',
        'http://127.0.0.1:8766/?x=1',
    ):
        with pytest.raises(ValueError):
            make_client(handler, base_url=invalid)


def test_status_uses_exact_local_bridge_route_and_hub_service_bearer() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured['method'] = request.method
        captured['url'] = str(request.url)
        captured['authorization'] = request.headers.get('authorization')
        return httpx.Response(200, json={'provider': 'openrouter', 'ready': True})

    result = pytest.run(asyncio=False) if False else None
    del result

    async def run() -> dict:
        return await make_client(handler).status()

    import asyncio
    payload = asyncio.run(run())
    assert payload == {'provider': 'openrouter', 'ready': True}
    assert captured == {
        'method': 'GET',
        'url': 'http://127.0.0.1:8766/api/openrouter/status',
        'authorization': f'Bearer {TOKEN}',
    }


def test_model_discovery_forwards_only_opaque_connection_and_idempotency() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured['path'] = request.url.path
        captured['body'] = json.loads(request.content)
        return httpx.Response(200, json={'models': [{'id': 'qwen/qwen3-coder'}]})

    async def run() -> dict:
        return await make_client(handler).list_models(
            connection_id=CONNECTION_ID,
            idempotency_key='openrouter-models-test-0001',
        )

    import asyncio
    payload = asyncio.run(run())
    assert payload['models'][0]['id'] == 'qwen/qwen3-coder'
    assert captured['path'] == '/api/openrouter/models'
    assert captured['body'] == {
        'connectionId': CONNECTION_ID,
        'idempotencyKey': 'openrouter-models-test-0001',
    }
    serialized = json.dumps(captured['body']).lower()
    assert 'api_key' not in serialized
    assert 'access_token' not in serialized


def test_chat_forwards_explicit_model_and_bounded_governance_metadata() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured['path'] = request.url.path
        captured['body'] = json.loads(request.content)
        return httpx.Response(200, json={
            'authorized': True,
            'receipt': {
                'outputs': {
                    'message': {'role': 'assistant', 'content': 'Hello from OpenRouter.'},
                    'returnedModel': 'qwen/qwen3-coder',
                },
            },
        })

    async def run() -> dict:
        return await make_client(handler).chat(
            workflow_run_id='chat-workflow-0001',
            delegation_id='inmyai-chat-0001',
            connection_id=CONNECTION_ID,
            model_id='qwen/qwen3-coder',
            idempotency_key='openrouter-chat-test-0001',
            input_sensitivity='INTERNAL',
            requested_output_tokens=512,
            messages=[
                {'role': 'system', 'content': 'Use project context.'},
                {'role': 'user', 'content': 'Say hello.'},
            ],
        )

    import asyncio
    payload = asyncio.run(run())
    assert payload['authorized'] is True
    assert captured['path'] == '/api/openrouter/chat'
    assert captured['body'] == {
        'workflowRunId': 'chat-workflow-0001',
        'delegationId': 'inmyai-chat-0001',
        'connectionId': CONNECTION_ID,
        'modelId': 'qwen/qwen3-coder',
        'idempotencyKey': 'openrouter-chat-test-0001',
        'inputSensitivity': 'INTERNAL',
        'requestedOutputTokens': 512,
        'inputs': {
            'messages': [
                {'role': 'system', 'content': 'Use project context.'},
                {'role': 'user', 'content': 'Say hello.'},
            ],
        },
    }


def test_http_and_network_errors_are_sanitized_without_token_or_body_leakage() -> None:
    async def http_failure() -> None:
        client = make_client(lambda request: httpx.Response(502, json={
            'code': 'CONNECT_UPSTREAM_FAILED',
            'detail': f'secret body {TOKEN}',
        }))
        with pytest.raises(ConnectOpenRouterError) as raised:
            await client.status()
        message = str(raised.value)
        assert '502' in message
        assert 'CONNECT_UPSTREAM_FAILED' in message
        assert 'secret body' not in message
        assert TOKEN not in message

    def network_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f'socket secret {TOKEN}', request=request)

    async def network_failure() -> None:
        client = make_client(network_handler)
        with pytest.raises(ConnectOpenRouterError) as raised:
            await client.status()
        assert str(raised.value) == 'InMyConnect local runtime is unavailable.'
        assert TOKEN not in str(raised.value)

    import asyncio
    asyncio.run(http_failure())
    asyncio.run(network_failure())


def test_client_rejects_invalid_model_connection_and_secret_shaped_message_fields_before_network() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    client = make_client(handler)

    async def run() -> None:
        with pytest.raises(ValueError):
            await client.list_models(connection_id='not-a-connection', idempotency_key='valid-idem-0001')
        with pytest.raises(ValueError):
            await client.chat(
                workflow_run_id='workflow-001',
                delegation_id='delegation-001',
                connection_id=CONNECTION_ID,
                model_id='bad model',
                idempotency_key='valid-idem-0002',
                input_sensitivity='INTERNAL',
                requested_output_tokens=512,
                messages=[{'role': 'user', 'content': 'hello'}],
            )
        with pytest.raises(ValueError):
            await client.chat(
                workflow_run_id='workflow-001',
                delegation_id='delegation-001',
                connection_id=CONNECTION_ID,
                model_id='qwen/qwen3-coder',
                idempotency_key='valid-idem-0003',
                input_sensitivity='SENSITIVE',
                requested_output_tokens=512,
                messages=[{'role': 'user', 'content': 'hello'}],
            )

    import asyncio
    asyncio.run(run())
    assert calls == 0


def test_connect_client_source_has_no_provider_endpoint_or_provider_credential_lookup() -> None:
    source = Path('services/api/app/connect_openrouter.py').read_text(encoding='utf-8')
    lowered = source.lower()
    for forbidden in (
        'openrouter.ai',
        'api.openai.com',
        'openrouter_api_key',
        'openai_api_key',
        'os.environ',
        'getenv(',
        'subprocess',
        'models: [',
        'fallbacks: [',
    ):
        assert forbidden not in lowered, forbidden
    assert '/api/openrouter/models' in source
    assert '/api/openrouter/chat' in source
    assert 'follow_redirects=False' in source
