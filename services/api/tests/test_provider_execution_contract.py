from __future__ import annotations

from pathlib import Path

import pytest

from services.api.app.provider_execution_contract import (
    CONNECT_ACTION_MODES,
    CONNECT_GOVERNED_REF,
    CONNECT_RISK_CLASSES,
    HUB_AGENT_ALLOWED_SUBJECT_MODES,
    HUB_EXECUTION_ENABLED,
    HUB_GOVERNANCE_REF,
    HUB_R1_DECISION,
    plan_governed_provider_execution,
)


BASE_PAYLOAD = {
    'provider_id': 'openai',
    'model_id': 'user-chosen-model',
    'data_sensitivity': 'INTERNAL',
    'input_bytes': 4096,
    'requested_output_tokens': 1024,
    'idempotency_key': 'phase5-contract-0001',
    'input_digest': 'sha256:' + ('a' * 64),
}


def blocker_codes(plan: dict) -> set[str]:
    return {item['code'] for item in plan['blockers']}


def test_current_upstream_governance_snapshot_is_pinned_fail_closed() -> None:
    assert HUB_GOVERNANCE_REF == 'cb660413941075337bd14aafedc79f998e01727a'
    assert CONNECT_GOVERNED_REF == '08b381203e8a3b7c379a1b7da3683a286b91d9f7'
    assert HUB_EXECUTION_ENABLED is False
    assert HUB_R1_DECISION == 'plan-only'
    assert HUB_AGENT_ALLOWED_SUBJECT_MODES == ('mutate',)
    assert CONNECT_ACTION_MODES == ('read',)
    assert CONNECT_RISK_CLASSES == ('R0',)


def test_valid_r1_execution_intent_remains_not_authorized() -> None:
    plan = plan_governed_provider_execution(BASE_PAYLOAD)
    assert plan['execution_status'] == 'EXECUTION_NOT_AUTHORIZED'
    assert plan['readiness'] == 'BLOCKED_UPSTREAM_CAPABILITY_GAP'
    assert plan['provider'] == 'openai'
    assert plan['model'] == 'user-chosen-model'
    assert plan['risk_class'] == 'R1'
    assert plan['selection_status'] == 'SELECTED_NOT_EXECUTABLE'
    assert plan['network_call_performed'] is False
    assert plan['provider_dispatch_performed'] is False
    assert plan['credential_resolution_performed'] is False
    assert plan['hub_authorization_performed'] is False
    assert plan['automatic_routing_allowed'] is False
    assert plan['silent_fallback_allowed'] is False
    assert plan['fallback_performed'] is False
    assert plan['next_gate'] == 'HUB_R1_EXECUTION_AUTHORITY_AND_CONNECT_R1_MODEL_API_EXECUTOR'

    codes = blocker_codes(plan)
    assert 'PROVIDER_DESCRIPTOR_CONTRACT_ONLY' in codes
    assert 'HUB_EXECUTION_DISABLED' in codes
    assert 'HUB_R1_PLAN_ONLY' in codes
    assert 'HUB_AGENT_EXECUTE_DELEGATION_UNAVAILABLE' in codes
    assert 'CONNECT_R1_MODEL_EXECUTOR_UNAVAILABLE' in codes
    assert 'CONNECT_CONNECTION_NOT_BOUND' in codes


def test_opaque_connection_id_is_metadata_only_and_not_resolved() -> None:
    payload = {**BASE_PAYLOAD, 'connection_id': 'conn_' + ('a' * 16)}
    plan = plan_governed_provider_execution(payload)
    assert plan['connection_id'] == payload['connection_id']
    assert plan['connection_binding_status'] == 'OPAQUE_ID_ACCEPTED_NOT_RESOLVED'
    assert plan['connect_boundary']['credential_handle_prefix'] == 'crf_'
    assert plan['connect_boundary']['raw_credential_exposure_allowed'] is False
    assert plan['connect_boundary']['credential_resolution_performed'] is False
    assert 'CONNECT_CONNECTION_NOT_BOUND' not in blocker_codes(plan)
    assert plan['execution_status'] == 'EXECUTION_NOT_AUTHORIZED'


def test_sensitive_and_restricted_exports_fail_closed_as_policy_blockers() -> None:
    for sensitivity in ('SENSITIVE', 'RESTRICTED'):
        plan = plan_governed_provider_execution({**BASE_PAYLOAD, 'data_sensitivity': sensitivity})
        assert 'EXPORT_SENSITIVITY_BLOCKED' in blocker_codes(plan)
        assert plan['provider_limits']['allowed_sensitivity'] == ['PUBLIC', 'INTERNAL']
        assert plan['provider_limits']['blocked_sensitivity'] == ['SENSITIVE', 'RESTRICTED']
        assert plan['provider_dispatch_performed'] is False


def test_provider_byte_and_output_limits_are_planned_without_execution() -> None:
    too_large = plan_governed_provider_execution({**BASE_PAYLOAD, 'input_bytes': 262_145})
    too_many_tokens = plan_governed_provider_execution({**BASE_PAYLOAD, 'requested_output_tokens': 8_193})
    assert 'PROVIDER_INPUT_LIMIT_EXCEEDED' in blocker_codes(too_large)
    assert 'PROVIDER_OUTPUT_LIMIT_EXCEEDED' in blocker_codes(too_many_tokens)
    assert too_large['provider_limits']['max_input_bytes'] == 262_144
    assert too_many_tokens['provider_limits']['max_output_tokens'] == 8_192


def test_execution_intent_digest_is_deterministic_and_payload_bound() -> None:
    first = plan_governed_provider_execution(BASE_PAYLOAD)
    second = plan_governed_provider_execution(dict(BASE_PAYLOAD))
    changed = plan_governed_provider_execution({**BASE_PAYLOAD, 'input_digest': 'sha256:' + ('b' * 64)})
    assert first['intent_digest'] == second['intent_digest']
    assert first['intent_digest'].startswith('sha256:')
    assert first['intent_digest'] != changed['intent_digest']


@pytest.mark.parametrize(
    'payload',
    [
        {},
        {**BASE_PAYLOAD, 'provider_id': 'unknown'},
        {**BASE_PAYLOAD, 'model_id': ' model'},
        {**BASE_PAYLOAD, 'data_sensitivity': 'SECRET'},
        {**BASE_PAYLOAD, 'input_bytes': -1},
        {**BASE_PAYLOAD, 'input_bytes': True},
        {**BASE_PAYLOAD, 'requested_output_tokens': 0},
        {**BASE_PAYLOAD, 'idempotency_key': 'short'},
        {**BASE_PAYLOAD, 'input_digest': 'sha256:bad'},
        {**BASE_PAYLOAD, 'connection_id': 'not-a-connection'},
        {**BASE_PAYLOAD, 'prompt': 'raw content must not enter this planner'},
        {**BASE_PAYLOAD, 'api_key': 'must-never-be-accepted'},
        {**BASE_PAYLOAD, 'access_token': 'must-never-be-accepted'},
        {**BASE_PAYLOAD, 'password': 'must-never-be-accepted'},
    ],
)
def test_execution_plan_payload_fails_closed(payload: dict) -> None:
    with pytest.raises(ValueError):
        plan_governed_provider_execution(payload)


def test_execution_plan_response_contains_no_raw_content_or_secret_material() -> None:
    plan = plan_governed_provider_execution(BASE_PAYLOAD)
    serialized = str(plan).lower()
    assert 'raw content must not enter' not in serialized
    for forbidden in ('api_key', 'apikey', 'access_token', 'refresh_token', 'password', 'bearer '):
        assert forbidden not in serialized


def test_execution_contract_source_has_no_network_or_provider_dispatch_primitives() -> None:
    source = Path('services/api/app/provider_execution_contract.py').read_text(encoding='utf-8').lower()
    for forbidden in (
        'httpx',
        'requests',
        'urllib.request',
        'socket.',
        'subprocess',
        'api.openai.com',
        '/responses',
        'authorization:',
        'os.environ',
        'getenv(',
    ):
        assert forbidden not in source, forbidden


def test_execution_contract_pins_exact_governance_paths_and_no_silent_fallback() -> None:
    plan = plan_governed_provider_execution(BASE_PAYLOAD)
    assert plan['hub_authority']['policy_path'] == 'data/policy/authority-policy.json'
    assert plan['hub_authority']['execution_enabled'] is False
    assert plan['hub_authority']['risk_decision'] == 'plan-only'
    assert plan['connect_boundary']['model_path'] == 'src/connect-model.mjs'
    assert plan['connect_boundary']['governed_executor_path'] == 'src/connect-hub-governed-executor.mjs'
    assert plan['connect_boundary']['current_action_modes'] == ['read']
    assert plan['connect_boundary']['current_risk_classes'] == ['R0']
    assert plan['silent_fallback_allowed'] is False
