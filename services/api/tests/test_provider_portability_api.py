from __future__ import annotations

from typing import get_args

import pytest
from fastapi.testclient import TestClient

from services.api.app.main import app
from services.api.app.schemas import ChatRequest


client = TestClient(app)


def test_portable_provider_catalog_endpoint_exposes_governed_openrouter() -> None:
    response = client.get('/api/providers/portable')
    assert response.status_code == 200, response.text
    catalog = response.json()
    assert len(catalog) == 1
    provider = catalog[0]
    assert provider['provider_id'] == 'openrouter'
    assert provider['display_name'] == 'OpenRouter'
    assert provider['transport'] == 'official-api-via-inmyconnect'
    assert provider['connection_owner'] == 'InMyConnect'
    assert provider['selection_mode'] == 'manual-only'
    assert provider['execution_state'] == 'hub-governed'
    assert provider['automatic_routing_allowed'] is False
    assert provider['dispatch_allowed'] is True
    assert provider['raw_credential_exposure_allowed'] is False
    assert provider['browser_session_credentials_allowed'] is False
    assert provider['model_discovery_state'] == 'account-filtered-live-via-connect'
    assert provider['default_model'] is None


def test_portable_provider_selection_endpoint_returns_governed_plan() -> None:
    response = client.post('/api/providers/portable/select', json={
        'provider_id': 'openrouter',
        'model_id': 'qwen/qwen3-coder',
        'selection_mode': 'manual',
    })
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan['provider'] == 'openrouter'
    assert plan['model'] == 'qwen/qwen3-coder'
    assert plan['selection_status'] == 'SELECTED_GOVERNED_PATH'
    assert plan['credential_resolution'] == 'INMYCONNECT_ONLY'
    assert plan['automatic_routing_allowed'] is False
    assert plan['dispatch_allowed'] is True
    assert plan['network_call_performed'] is False
    assert plan['raw_credential_exposure_allowed'] is False
    assert plan['browser_session_credentials_allowed'] is False
    assert plan['next_gate'] == 'CONNECT_RUNTIME_AND_HUB_SERVICE_IDENTITY'


@pytest.mark.parametrize(
    'payload',
    [
        {},
        {'provider_id': 'openrouter'},
        {'provider_id': 'openrouter', 'model_id': ''},
        {'provider_id': 'unknown', 'model_id': 'model-id'},
        {'provider_id': 'openrouter', 'model_id': ' model-id'},
        {'provider_id': 'openrouter', 'model_id': 'model id'},
        {'provider_id': 'openrouter', 'model_id': 'model-id', 'selection_mode': 'auto'},
        {'provider_id': 123, 'model_id': 'model-id'},
        {'provider_id': 'openrouter', 'model_id': 123},
        {'provider_id': 'openrouter', 'model_id': 'model-id', 'selection_mode': False},
    ],
)
def test_portable_provider_selection_endpoint_fails_closed(payload: dict) -> None:
    response = client.post('/api/providers/portable/select', json=payload)
    assert response.status_code == 400, response.text


def test_chat_execution_provider_schema_adds_openrouter_but_not_direct_openai() -> None:
    annotation = ChatRequest.model_fields['provider'].annotation
    assert set(get_args(annotation)) == {'auto', 'mock', 'ollama', 'openrouter'}


def test_chat_request_rejects_direct_openai_as_execution_provider_before_dispatch() -> None:
    response = client.post('/api/chat', json={
        'project_id': 1,
        'message': 'Direct OpenAI must not be the Phase 5 execution target.',
        'provider': 'openai',
        'model': 'user-chosen-model',
    })
    assert response.status_code == 422, response.text


def test_openrouter_chat_schema_contains_only_opaque_connection_and_no_provider_credential_field() -> None:
    fields = set(ChatRequest.model_fields)
    assert {'connection_id', 'idempotency_key', 'input_sensitivity', 'requested_output_tokens'} <= fields
    for forbidden in ('api_key', 'apikey', 'access_token', 'refresh_token', 'password', 'credential', 'openrouter_api_key'):
        assert forbidden not in fields


def test_portable_selection_response_contains_no_credentials_or_secret_material() -> None:
    plan = client.post('/api/providers/portable/select', json={
        'provider_id': 'openrouter',
        'model_id': 'qwen/qwen3-coder',
        'selection_mode': 'manual',
    }).json()
    serialized = str(plan).lower()
    for forbidden in ('api_key', 'apikey', 'authorization', 'bearer ', 'cookie', 'access_token', 'refresh_token'):
        assert forbidden not in serialized


def test_models_status_discloses_only_boolean_hub_identity_state() -> None:
    response = client.get('/api/models/status')
    assert response.status_code == 200, response.text
    payload = response.json()
    openrouter = payload['openrouter']
    assert openrouter['provider'] == 'openrouter'
    assert openrouter['governed'] is True
    assert isinstance(openrouter['hub_service_identity_configured'], bool)
    assert openrouter['raw_provider_credential_in_inmyai'] is False
    serialized = str(openrouter).lower()
    assert 'bearer ' not in serialized
    assert 'api_key' not in serialized
