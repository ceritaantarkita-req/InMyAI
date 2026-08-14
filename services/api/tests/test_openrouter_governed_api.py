from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.api.app import main
from services.api.app.connect_openrouter import ConnectOpenRouterError
from services.api.app.schemas import ChatRequest


client = TestClient(main.app)
CONNECTION_ID = 'conn_' + ('a' * 16)


class StubConnectClient:
    def __init__(self) -> None:
        self.model_calls: list[dict[str, Any]] = []
        self.chat_calls: list[dict[str, Any]] = []

    async def status(self) -> dict:
        return {'provider': 'openrouter', 'ready': True}

    async def list_models(self, **kwargs) -> dict:
        self.model_calls.append(kwargs)
        return {
            'provider': 'openrouter',
            'models': [
                {'id': 'qwen/qwen3-coder', 'name': 'Qwen3 Coder'},
                {'id': 'anthropic/claude-sonnet-4.5', 'name': 'Claude Sonnet 4.5'},
            ],
            'truncated': False,
        }

    async def chat(self, **kwargs) -> dict:
        self.chat_calls.append(kwargs)
        return {
            'authorized': True,
            'receipt': {
                'outputs': {
                    'provider': 'openrouter',
                    'returnedModel': kwargs['model_id'],
                    'message': {'role': 'assistant', 'content': 'Governed answer.'},
                },
            },
            'hubReceiptId': 'hub-receipt-test',
        }


def test_openrouter_model_endpoint_forwards_opaque_metadata_only(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = StubConnectClient()
    monkeypatch.setattr(main, '_openrouter_client', lambda: stub)

    response = client.post('/api/providers/openrouter/models', json={
        'connection_id': CONNECTION_ID,
        'idempotency_key': 'openrouter-models-api-0001',
    })
    assert response.status_code == 200, response.text
    assert [item['id'] for item in response.json()['models']] == [
        'qwen/qwen3-coder',
        'anthropic/claude-sonnet-4.5',
    ]
    assert stub.model_calls == [{
        'connection_id': CONNECTION_ID,
        'idempotency_key': 'openrouter-models-api-0001',
    }]
    serialized = str(stub.model_calls).lower()
    assert 'api_key' not in serialized
    assert 'bearer ' not in serialized


def test_openrouter_model_endpoint_requires_explicit_connection_and_idempotency(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = StubConnectClient()
    monkeypatch.setattr(main, '_openrouter_client', lambda: stub)
    for payload in ({}, {'connection_id': CONNECTION_ID}, {'idempotency_key': 'valid-idempotency-0001'}):
        response = client.post('/api/providers/openrouter/models', json=payload)
        assert response.status_code == 400, response.text
    assert stub.model_calls == []


class FakeTransaction:
    def __init__(self) -> None:
        self.executions: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, statement: str, params: tuple[Any, ...]) -> SimpleNamespace:
        self.executions.append((statement, params))
        return SimpleNamespace(lastrowid=77)


@contextmanager
def fake_transaction():
    yield FakeTransaction()


def test_explicit_openrouter_chat_uses_governed_client_without_auto_route_or_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = StubConnectClient()
    monkeypatch.setattr(main, '_openrouter_client', lambda: stub)
    monkeypatch.setattr(main, 'transaction', fake_transaction)
    monkeypatch.setattr(main.services, 'build_context', lambda project_id, message, max_chars: ('verified local context', []))
    monkeypatch.setattr(main, 'utc_now', lambda: '2026-08-14T16:00:00Z')

    async def ollama_status() -> dict:
        return {'available': False, 'models': []}

    monkeypatch.setattr(main, 'get_ollama_status', ollama_status)

    async def forbidden_mock(*args, **kwargs):
        raise AssertionError('Mock fallback must not run for explicit OpenRouter.')

    monkeypatch.setattr(main.MockProvider, 'chat', forbidden_mock)

    result = asyncio.run(main.chat(ChatRequest(
        project_id=9,
        message='Use the project context and answer.',
        provider='openrouter',
        model='qwen/qwen3-coder',
        connection_id=CONNECTION_ID,
        idempotency_key='openrouter-chat-api-0001',
        input_sensitivity='INTERNAL',
        requested_output_tokens=512,
    )))

    assert result['answer'] == 'Governed answer.'
    assert result['provider'] == 'openrouter'
    assert result['model'] == 'qwen/qwen3-coder'
    assert result['route']['provider'] == 'openrouter'
    assert 'automatic routing and fallback are disabled' in result['route']['reason']
    assert len(stub.chat_calls) == 1
    call = stub.chat_calls[0]
    assert call['connection_id'] == CONNECTION_ID
    assert call['model_id'] == 'qwen/qwen3-coder'
    assert call['idempotency_key'] == 'openrouter-chat-api-0001'
    assert call['input_sensitivity'] == 'INTERNAL'
    assert call['requested_output_tokens'] == 512
    assert call['messages'][-1] == {'role': 'user', 'content': 'Use the project context and answer.'}


def test_openrouter_failure_is_returned_safely_and_never_falls_back_to_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingClient(StubConnectClient):
        async def chat(self, **kwargs) -> dict:
            raise ConnectOpenRouterError('InMyConnect request failed with status 503 (CONNECT_UNAVAILABLE).', status_code=503)

    monkeypatch.setattr(main, '_openrouter_client', lambda: FailingClient())
    monkeypatch.setattr(main, 'transaction', fake_transaction)
    monkeypatch.setattr(main.services, 'build_context', lambda project_id, message, max_chars: ('context', []))
    monkeypatch.setattr(main, 'utc_now', lambda: '2026-08-14T16:00:00Z')

    async def ollama_status() -> dict:
        return {'available': False, 'models': []}

    monkeypatch.setattr(main, 'get_ollama_status', ollama_status)
    mock_calls = 0

    async def forbidden_mock(*args, **kwargs):
        nonlocal mock_calls
        mock_calls += 1
        raise AssertionError('Mock fallback must not run.')

    monkeypatch.setattr(main.MockProvider, 'chat', forbidden_mock)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(main.chat(ChatRequest(
            project_id=9,
            message='Fail safely.',
            provider='openrouter',
            model='qwen/qwen3-coder',
            connection_id=CONNECTION_ID,
            idempotency_key='openrouter-chat-api-0002',
        )))
    assert raised.value.status_code == 503
    assert 'CONNECT_UNAVAILABLE' in raised.value.detail
    assert mock_calls == 0


def test_openrouter_runtime_source_contains_no_direct_provider_endpoint_or_provider_key() -> None:
    main_source = Path('services/api/app/main.py').read_text(encoding='utf-8').lower()
    client_source = Path('services/api/app/connect_openrouter.py').read_text(encoding='utf-8').lower()
    combined = main_source + '\n' + client_source
    for forbidden in (
        'openrouter.ai',
        'api.openai.com',
        'openrouter_api_key',
        'openai_api_key',
    ):
        assert forbidden not in combined, forbidden
    assert '/api/providers/openrouter/models' in main_source
    assert "provider='openrouter'" in main_source
    assert 'without fallback' in main_source
