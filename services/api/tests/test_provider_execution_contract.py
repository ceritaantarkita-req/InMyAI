from __future__ import annotations

from pathlib import Path

import pytest

from services.api.app.provider_execution_contract import (
    CONNECT_ACTION_MODES,
    CONNECT_GOVERNED_REF,
    CONNECT_HTTP_BRIDGE_STATE,
    CONNECT_RISK_CLASSES,
    HUB_AGENT_ALLOWED_SUBJECT_MODES,
    HUB_EXECUTION_ENABLED,
    HUB_GOVERNANCE_REF,
    HUB_R1_DECISION,
    HUB_R1_SERVICE_IDENTITY,
    plan_governed_provider_execution,
)


BASE_PAYLOAD = {
    'provider_id': 'openrouter',
    'model_id': 'qwen/qwen3-coder',
    'data_sensitivity': 'INTERNAL',
    'input_bytes': 4096,
    'requested_output_tokens': 1024,
    'idempotency_key': 'phase5-contract-0001',
    'input_digest': 'sha256:' + ('a' * 64),
}


def blocker_codes(plan: dict) -> set[str]:
    return {item['code'] for item in plan['blockers']}


def test_current_upstream_governance_snapshot_is_pinned_to_accepted_runtime() -> None:
    assert HUB_GOVERNANCE_REF == 'dbfbb3d3fa1c6e5ff217814e8bfbb8ef5c5cc1b7'
    assert CONNECT_GOVERNED_REF == '65d8be8692da237961dc19a76147bab8739c8597'
    assert HUB_EXECUTION_ENABLED is True
    assert HUB_R1_DECISION == 'execute'
    assert HUB_R1_SERVICE_IDENTITY == 'agent:inmyai'
    assert HUB_AGENT_ALLOWED_SUBJECT_MODES == ('mutate',)
    assert CONNECT_ACTION_MODES == ('read', 'model-api')
    assert CONNECT_RISK_CLASSES == ('R0', 'R1')
    assert CONNECT_HTTP_BRIDGE_STATE == 'required-next-runtime-boundary'


def test_valid_r1_execution_intent_without_connection_is_not_ready() -> None:
    plan = plan_governed_provider_execution(BASE_PAYLOAD)
    assert plan['execution_status'] == 'EXECUTION_NOT_READY'
    assert plan['readiness'] == 'BLOCKED_INPUT_OR_CONNECTION_POLICY'
    assert plan['provider'] == 'openrouter'
    assert plan['model'] == 'qwen/qwen3-coder'
    assert plan['risk_class'] == 'R1'
    assert plan['selection_status'] == 'SELECTED_GOVERNED_PATH'
    assert plan['network_call_performed'] is False
    assert plan['provider_dispatch_performed'] is False
    assert plan['credential_resolution_performed'] is False
    assert plan['hub_authorization_performed'] is False
    assert plan['automatic_routing_allowed'] is False
    assert plan['silent_fallback_allowed'] is False
    assert plan['fallback_performed'] is False
    assert plan['next_gate'] == 'CONNECT_HTTP_BRIDGE_RUNTIME'
    assert blocker_codes(plan) == {'CONNECT_CONNECTION_NOT_BOUND'}


def test_opaque_connection_id_makes_intent_ready_for_connect_http_runtime() -> None:
    payload = {**BASE_PAYLOAD, 'connection_id': 'conn_' + ('a' * 16)}
    plan = plan_governed_provider_execution(payload)
    assert plan['connection_id'] == payload['connection_id']
    assert plan['connection_binding_status'] == 'OPAQUE_ID_ACCEPTED_NOT_RESOLVED'
    assert plan['connect_boundary']['credential_handle_prefix'] == 'crf_'
    assert plan['connect_boundary']['raw_credential_exposure_allowed'] is False
    assert plan['connect_boundary']['credential_resolution_performed'] is False
    assert plan['connect_boundary']['http_bridge_state'] == 'required-next-runtime-boundary'
    assert plan['execution_status'] == 'GOVERNED_EXECUTION_READY'
    assert plan['readiness'] == 'READY_FOR_CONNECT_HTTP_RUNTIME'
    assert plan['blockers'] == []


def test_hub_and_connect_capability_gap_is_closed_without_changing_phase_e_mutation_modes() -> None:
    plan = plan_governed_provider_execution({**BASE_PAYLOAD, 'connection_id': 'conn_' + ('b' * 16)})
    assert plan['hub_authority']['policy_path'] == 'data/policy/provider-execution-r1-policy.json'
    assert plan['hub_authority']['execution_enabled'] is True
    assert plan['hub_authority']['risk_decision'] == 'execute'
    assert plan['hub_authority']['service_identity'] == 'agent:inmyai'
    assert plan['hub_authority']['phase_e_agent_allowed_subject_modes'] == ['mutate']
    assert plan['connect_boundary']['model_path'] == 'src/connect-model-r1-executor.mjs'
    assert plan['connect_boundary']['governed_executor_path'] == 'src/connect-openrouter-governed-runtime.mjs'
    assert plan['connect_boundary']['hub_client_path'] == 'src/connect-hub-r1-http-client.mjs'
    assert plan['connect_boundary']['current_action_modes'] == ['read', 'model-api']
    assert plan['connect_boundary']['current_risk_classes'] == ['R0', 'R1']


def test_sensitive_and_restricted_exports_fail_closed_as_policy_blockers() -> None:
    for sensitivity in ('SENSITIVE', 'RESTRICTED'):
        plan = plan_governed_provider_execution({
            **BASE_PAYLOAD,
            'connection_id': 'conn_' + ('c' * 16),
            'data_sensitivity': sensitivity,
        })
        assert 'EXPORT_SENSITIVITY_BLOCKED' in blocker_codes(plan)
        assert plan['provider_limits']['allowed_sensitivity'] == ['PUBLIC', 'INTERNAL']
        assert plan['provider_limits']['blocked_sensitivity'] == ['SENSITIVE', 'RESTRICTED']
        assert plan['provider_dispatch_performed'] is False


def test_provider_byte_and_output_limits_are_planned_without_execution() -> None:
    connection = {'connection_id': 'conn_' + ('d' * 16)}
    too_large = plan_governed_provider_execution({**BASE_PAYLOAD, **connection, 'input_bytes': 262_145})
    too_many_tokens = plan_governed_provider_execution({**BASE_PAYLOAD, **connection, 'requested_output_tokens': 8_193})
    assert 'PROVIDER_INPUT_LIMIT_EXCEEDED' in blocker_codes(too_large)
    assert 'PROVIDER_OUTPUT_LIMIT_EXCEEDED' in blocker_codes(too_many_tokens)
    assert too_large['provider_limits']['max_input_bytes'] == 262_144
    assert too_many_tokens['provider_limits']['max_output_tokens'] == 8_192


def test_execution_intent_digest_is_deterministic_and_payload_bound() -> None:
    payload = {**BASE_PAYLOAD, 'connection_id': 'conn_' + ('e' * 16)}
    first = plan_governed_provider_execution(payload)
    second = plan_governed_provider_execution(dict(payload))
    changed = plan_governed_provider_execution({**payload, 'input_digest': 'sha256:' + ('b' * 64)})
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
    plan = plan_governed_provider_execution({**BASE_PAYLOAD, 'connection_id': 'conn_' + ('f' * 16)})
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
        'openrouter.ai',
        'api.openai.com',
        '/chat/completions',
        'authorization:',
        'os.environ',
        'getenv(',
    ):
        assert forbidden not in source, forbidden


def test_execution_contract_still_forbids_automatic_routing_and_silent_fallback() -> None:
    plan = plan_governed_provider_execution({**BASE_PAYLOAD, 'connection_id': 'conn_' + ('g' * 16)})
    assert plan['automatic_routing_allowed'] is False
    assert plan['silent_fallback_allowed'] is False
    assert plan['fallback_performed'] is False
    assert plan['network_call_performed'] is False
    assert plan['provider_dispatch_performed'] is False
