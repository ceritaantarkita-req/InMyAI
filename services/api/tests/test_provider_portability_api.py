from __future__ import annotations

from typing import get_args

import pytest
from fastapi.testclient import TestClient

from services.api.app.main import app
from services.api.app.schemas import ChatRequest


client = TestClient(app)


def test_portable_provider_catalog_endpoint_exposes_contract_only_openai() -> None:
    response = client.get('/api/providers/portable')
    assert response.status_code == 200, response.text
    catalog = response.json()
    assert len(catalog) == 1
    provider = catalog[0]
    assert provider['provider_id'] == 'openai'
    assert provider['display_name'] == 'OpenAI API'
    assert provider['transport'] == 'official-api'
    assert provider['connection_owner'] == 'InMyConnect'
    assert provider['selection_mode'] == 'manual-only'
    assert provider['execution_state'] == 'contract-only'
    assert provider['automatic_routing_allowed'] is False
    assert provider['dispatch_allowed'] is False
    assert provider['raw_credential_exposure_allowed'] is False
    assert provider['browser_session_credentials_allowed'] is False
    assert provider['default_model'] is None


def test_portable_provider_selection_endpoint_returns_non_executable_plan() -> None:
    response = client.post('/api/providers/portable/select', json={
        'provider_id': 'openai',
        'model_id': 'user-chosen-model',
        'selection_mode': 'manual',
    })
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan['provider'] == 'openai'
    assert plan['model'] == 'user-chosen-model'
    assert plan['selection_status'] == 'SELECTED_NOT_EXECUTABLE'
    assert plan['credential_resolution'] == 'INMYCONNECT_ONLY'
    assert plan['automatic_routing_allowed'] is False
    assert plan['dispatch_allowed'] is False
    assert plan['network_call_performed'] is False
    assert plan['raw_credential_exposure_allowed'] is False
    assert plan['browser_session_credentials_allowed'] is False
    assert plan['next_gate'] == 'HUB_CONNECT_GOVERNED_PROVIDER_EXECUTION'


@pytest.mark.parametrize(
    'payload',
    [
        {},
        {'provider_id': 'openai'},
        {'provider_id': 'openai', 'model_id': ''},
        {'provider_id': 'unknown', 'model_id': 'model-id'},
        {'provider_id': 'openai', 'model_id': ' model-id'},
        {'provider_id': 'openai', 'model_id': 'model id'},
        {'provider_id': 'openai', 'model_id': 'model-id', 'selection_mode': 'auto'},
        {'provider_id': 123, 'model_id': 'model-id'},
        {'provider_id': 'openai', 'model_id': 123},
        {'provider_id': 'openai', 'model_id': 'model-id', 'selection_mode': False},
    ],
)
def test_portable_provider_selection_endpoint_fails_closed(payload: dict) -> None:
    response = client.post('/api/providers/portable/select', json=payload)
    assert response.status_code == 400, response.text


def test_chat_execution_provider_schema_remains_local_only() -> None:
    annotation = ChatRequest.model_fields['provider'].annotation
    assert set(get_args(annotation)) == {'auto', 'mock', 'ollama'}


def test_chat_request_rejects_openai_as_execution_provider_before_dispatch() -> None:
    response = client.post('/api/chat', json={
        'project_id': 1,
        'message': 'This must never dispatch to a portable provider in this checkpoint.',
        'provider': 'openai',
        'model': 'user-chosen-model',
    })
    assert response.status_code == 422, response.text


def test_portable_selection_response_contains_no_credentials_or_secret_material() -> None:
    plan = client.post('/api/providers/portable/select', json={
        'provider_id': 'openai',
        'model_id': 'user-chosen-model',
        'selection_mode': 'manual',
    }).json()
    serialized = str(plan).lower()
    for forbidden in ('api_key', 'apikey', 'authorization', 'bearer ', 'cookie', 'access_token', 'refresh_token'):
        assert forbidden not in serialized
