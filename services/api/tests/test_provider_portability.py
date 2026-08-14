from __future__ import annotations

from pathlib import Path

import pytest

from services.api.app.provider_portability import (
    CONNECT_OPENAI_DESCRIPTOR_PATH,
    CONNECT_PROVIDER_FOUNDATION_REF,
    CONNECT_PROVIDER_FOUNDATION_REPOSITORY,
    get_portable_provider_descriptor,
    list_portable_provider_catalog,
    plan_manual_provider_selection,
    portable_provider_is_execution_authorized,
)


def test_portable_provider_catalog_pins_accepted_connect_descriptor() -> None:
    catalog = list_portable_provider_catalog()
    assert len(catalog) == 1
    provider = catalog[0]
    assert provider['provider_id'] == 'openai'
    assert provider['display_name'] == 'OpenAI API'
    assert provider['transport'] == 'official-api'
    assert provider['connection_owner'] == 'InMyConnect'
    assert provider['descriptor_repository'] == CONNECT_PROVIDER_FOUNDATION_REPOSITORY
    assert provider['descriptor_ref'] == CONNECT_PROVIDER_FOUNDATION_REF
    assert provider['descriptor_path'] == CONNECT_OPENAI_DESCRIPTOR_PATH
    assert provider['execution_state'] == 'contract-only'
    assert provider['risk_class'] == 'R1'
    assert provider['selection_mode'] == 'manual-only'
    assert provider['automatic_routing_allowed'] is False
    assert provider['dispatch_allowed'] is False
    assert provider['credential_resolution'] == 'INMYCONNECT_ONLY'
    assert provider['raw_credential_exposure_allowed'] is False
    assert provider['browser_session_credentials_allowed'] is False
    assert provider['model_discovery_state'] == 'provider-discovery-later'
    assert provider['default_model'] is None
    assert provider['allowed_sensitivity'] == ('PUBLIC', 'INTERNAL')
    assert provider['blocked_sensitivity'] == ('SENSITIVE', 'RESTRICTED')
    assert provider['max_input_bytes'] == 262_144
    assert provider['max_output_tokens'] == 8_192


def test_single_descriptor_lookup_is_bounded_and_non_executable() -> None:
    provider = get_portable_provider_descriptor('openai')
    assert provider['provider_id'] == 'openai'
    assert provider['execution_state'] == 'contract-only'
    assert provider['dispatch_allowed'] is False
    with pytest.raises(ValueError):
        get_portable_provider_descriptor('unknown')


def test_manual_cloud_selection_requires_explicit_provider_and_model() -> None:
    plan = plan_manual_provider_selection('openai', 'example-model-id')
    assert plan['provider'] == 'openai'
    assert plan['model'] == 'example-model-id'
    assert plan['selection_mode'] == 'manual'
    assert plan['selection_status'] == 'SELECTED_NOT_EXECUTABLE'
    assert plan['descriptor'] == {
        'repository': CONNECT_PROVIDER_FOUNDATION_REPOSITORY,
        'ref': CONNECT_PROVIDER_FOUNDATION_REF,
        'path': CONNECT_OPENAI_DESCRIPTOR_PATH,
    }
    assert plan['connection_owner'] == 'InMyConnect'
    assert plan['credential_resolution'] == 'INMYCONNECT_ONLY'
    assert plan['risk_class'] == 'R1'
    assert plan['execution_state'] == 'contract-only'
    assert plan['allowed_sensitivity'] == ['PUBLIC', 'INTERNAL']
    assert plan['blocked_sensitivity'] == ['SENSITIVE', 'RESTRICTED']
    assert plan['max_input_bytes'] == 262_144
    assert plan['max_output_tokens'] == 8_192
    assert plan['raw_credential_exposure_allowed'] is False
    assert plan['browser_session_credentials_allowed'] is False
    assert plan['automatic_routing_allowed'] is False
    assert plan['dispatch_allowed'] is False
    assert plan['network_call_performed'] is False
    assert plan['next_gate'] == 'HUB_CONNECT_GOVERNED_PROVIDER_EXECUTION'


@pytest.mark.parametrize(
    ('provider', 'model', 'mode'),
    [
        ('openai', '', 'manual'),
        ('openai', ' model', 'manual'),
        ('openai', 'model ', 'manual'),
        ('openai', 'model id', 'manual'),
        ('openai', 'model?query=1', 'manual'),
        ('unknown', 'model-id', 'manual'),
        ('auto', 'model-id', 'manual'),
        ('openai', 'model-id', 'auto'),
        ('openai', 'model-id', 'shadow'),
    ],
)
def test_manual_cloud_selection_fails_closed_on_implicit_or_unbounded_choices(
    provider: str,
    model: str,
    mode: str,
) -> None:
    with pytest.raises(ValueError):
        plan_manual_provider_selection(provider, model, selection_mode=mode)


def test_portable_provider_execution_authority_is_fail_closed() -> None:
    assert portable_provider_is_execution_authorized('openai') is False
    assert portable_provider_is_execution_authorized('unknown') is False


def test_portability_source_has_no_network_or_secret_resolution_primitives() -> None:
    source = Path('services/api/app/provider_portability.py').read_text(encoding='utf-8')
    forbidden = [
        'httpx',
        'requests',
        'urllib.request',
        'socket.',
        'subprocess',
        'OPENAI_API_KEY',
        'Authorization:',
        'os.environ',
        'getenv(',
        'cookie',
        'session token',
    ]
    lowered = source.lower()
    for token in forbidden:
        assert token.lower() not in lowered, token


def test_portability_source_has_no_model_default_or_auto_cloud_route() -> None:
    source = Path('services/api/app/provider_portability.py').read_text(encoding='utf-8')
    assert "default_model=None" in source
    assert "selection_mode='manual-only'" in source
    assert 'automatic_routing_allowed=False' in source
    assert 'dispatch_allowed=False' in source
    assert 'SELECTED_NOT_EXECUTABLE' in source
    assert 'HUB_CONNECT_GOVERNED_PROVIDER_EXECUTION' in source
