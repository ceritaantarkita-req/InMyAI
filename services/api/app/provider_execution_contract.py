from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .provider_portability import get_portable_provider_descriptor, plan_manual_provider_selection


PHASE5_GOVERNED_EXECUTION_SCHEMA = '1.0.0'

HUB_GOVERNANCE_REPOSITORY = 'ceritaantarkita-req/inmyhub'
HUB_GOVERNANCE_REF = 'cb660413941075337bd14aafedc79f998e01727a'
HUB_AUTHORITY_POLICY_PATH = 'data/policy/authority-policy.json'
HUB_AUTHORITY_MODE = 'plan-only'
HUB_EXECUTION_ENABLED = False
HUB_R1_DECISION = 'plan-only'
HUB_AGENT_ALLOWED_SUBJECT_MODES = ('mutate',)

CONNECT_GOVERNED_REPOSITORY = 'ceritaantarkita-req/InMyConnect'
CONNECT_GOVERNED_REF = '08b381203e8a3b7c379a1b7da3683a286b91d9f7'
CONNECT_MODEL_PATH = 'src/connect-model.mjs'
CONNECT_GOVERNED_EXECUTOR_PATH = 'src/connect-hub-governed-executor.mjs'
CONNECT_VAULT_BOUNDARY_PATH = 'docs/connect-vault-boundary-v1.md'
CONNECT_ACTION_MODES = ('read',)
CONNECT_RISK_CLASSES = ('R0',)
CONNECT_CREDENTIAL_HANDLE_PREFIX = 'crf_'

_ALLOWED_FIELDS = {
    'provider_id',
    'model_id',
    'data_sensitivity',
    'input_bytes',
    'requested_output_tokens',
    'idempotency_key',
    'input_digest',
    'connection_id',
}
_REQUIRED_FIELDS = _ALLOWED_FIELDS - {'connection_id'}
_SECRETISH_KEY = re.compile(
    r'(^|[_-])(access[_-]?token|refresh[_-]?token|api[_-]?key|private[_-]?key|password|passphrase|credential[_-]?value|secret)($|[_-])',
    re.IGNORECASE,
)
_CONNECTION_ID = re.compile(r'^conn_[A-Za-z0-9_-]{16,96}$')
_IDEMPOTENCY_KEY = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/-]{7,255}$')
_INPUT_DIGEST = re.compile(r'^sha256:[0-9a-f]{64}$')
_SENSITIVITY = {'PUBLIC', 'INTERNAL', 'SENSITIVE', 'RESTRICTED'}


def _fail(message: str) -> None:
    raise ValueError(message)


def _bounded_string(value: Any, label: str, *, min_length: int = 1, max_length: int = 256) -> str:
    if not isinstance(value, str) or not (min_length <= len(value) <= max_length) or '\x00' in value:
        _fail(f'{label} must be a bounded NUL-free string.')
    if value.strip() != value:
        _fail(f'{label} cannot have surrounding whitespace.')
    return value


def _bounded_int(value: Any, label: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum or value > maximum:
        _fail(f'{label} must be an integer between {minimum} and {maximum}.')
    return value


def _add_blocker(blockers: list[dict[str, str]], code: str, message: str) -> None:
    if not any(item['code'] == code for item in blockers):
        blockers.append({'code': code, 'message': message})


def _intent_digest(value: dict[str, Any]) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def plan_governed_provider_execution(payload: dict[str, Any]) -> dict[str, Any]:
    """Plan a future Hub + Connect governed provider execution without executing it.

    This boundary intentionally accepts metadata and an input digest only. Raw
    prompt/content and credential material do not belong in this planning API.
    The current upstream Hub/Connect refs are pinned below and are evaluated
    fail-closed: Hub is plan-only for R1 and Connect currently exposes read/R0
    execution only, so an OpenAI R1 model execution cannot be authorized here.
    """

    if not isinstance(payload, dict):
        _fail('execution plan payload must be an object.')

    for key in payload:
        if not isinstance(key, str):
            _fail('execution plan field names must be strings.')
        if _SECRETISH_KEY.search(key):
            _fail(f'execution plan cannot contain credential-like field: {key}.')
        if key not in _ALLOWED_FIELDS:
            _fail(f'execution plan has unknown field: {key}.')

    missing = sorted(_REQUIRED_FIELDS - payload.keys())
    if missing:
        _fail(f"execution plan is missing required field(s): {', '.join(missing)}.")

    provider_id = _bounded_string(payload['provider_id'], 'provider_id', max_length=64)
    model_id = _bounded_string(payload['model_id'], 'model_id', max_length=128)
    selection = plan_manual_provider_selection(provider_id, model_id, selection_mode='manual')
    descriptor = get_portable_provider_descriptor(provider_id)

    sensitivity = _bounded_string(payload['data_sensitivity'], 'data_sensitivity', max_length=16)
    if sensitivity not in _SENSITIVITY:
        _fail('data_sensitivity is invalid.')

    input_bytes = _bounded_int(payload['input_bytes'], 'input_bytes', minimum=0, maximum=1_073_741_824)
    requested_output_tokens = _bounded_int(
        payload['requested_output_tokens'],
        'requested_output_tokens',
        minimum=1,
        maximum=1_000_000,
    )

    idempotency_key = _bounded_string(payload['idempotency_key'], 'idempotency_key', min_length=8, max_length=256)
    if not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
        _fail('idempotency_key is invalid.')

    input_digest = _bounded_string(payload['input_digest'], 'input_digest', max_length=71)
    if not _INPUT_DIGEST.fullmatch(input_digest):
        _fail('input_digest must be sha256:<64 lowercase hex characters>.')

    connection_id = payload.get('connection_id')
    if connection_id is not None:
        connection_id = _bounded_string(connection_id, 'connection_id', max_length=101)
        if not _CONNECTION_ID.fullmatch(connection_id):
            _fail('connection_id is invalid.')

    blockers: list[dict[str, str]] = []

    if descriptor['execution_state'] != 'authorized' or descriptor['dispatch_allowed'] is not True:
        _add_blocker(
            blockers,
            'PROVIDER_DESCRIPTOR_CONTRACT_ONLY',
            'The accepted portable-provider descriptor does not authorize provider dispatch.',
        )

    if HUB_EXECUTION_ENABLED is not True:
        _add_blocker(
            blockers,
            'HUB_EXECUTION_DISABLED',
            'The pinned InMyHub authority policy is plan-only with executionEnabled=false.',
        )

    if descriptor['risk_class'] == 'R1' and HUB_R1_DECISION != 'execute-eligible':
        _add_blocker(
            blockers,
            'HUB_R1_PLAN_ONLY',
            'The pinned InMyHub authority policy classifies R1 as plan-only.',
        )

    if 'execute' not in HUB_AGENT_ALLOWED_SUBJECT_MODES:
        _add_blocker(
            blockers,
            'HUB_AGENT_EXECUTE_DELEGATION_UNAVAILABLE',
            'The pinned InMyHub agent delegation policy does not authorize execute-mode delegation.',
        )

    if descriptor['risk_class'] not in CONNECT_RISK_CLASSES or 'model-api' not in CONNECT_ACTION_MODES:
        _add_blocker(
            blockers,
            'CONNECT_R1_MODEL_EXECUTOR_UNAVAILABLE',
            'The pinned InMyConnect execution foundation is read/R0-only and has no R1 model-API executor.',
        )

    if connection_id is None:
        _add_blocker(
            blockers,
            'CONNECT_CONNECTION_NOT_BOUND',
            'No opaque InMyConnect connection_id is bound to this execution intent.',
        )

    if sensitivity not in set(descriptor['allowed_sensitivity']):
        _add_blocker(
            blockers,
            'EXPORT_SENSITIVITY_BLOCKED',
            f'{sensitivity} is not allowed by the accepted provider descriptor export boundary.',
        )

    if input_bytes > descriptor['max_input_bytes']:
        _add_blocker(
            blockers,
            'PROVIDER_INPUT_LIMIT_EXCEEDED',
            f"input_bytes exceeds the accepted provider limit of {descriptor['max_input_bytes']} bytes.",
        )

    if requested_output_tokens > descriptor['max_output_tokens']:
        _add_blocker(
            blockers,
            'PROVIDER_OUTPUT_LIMIT_EXCEEDED',
            f"requested_output_tokens exceeds the accepted provider limit of {descriptor['max_output_tokens']}.",
        )

    intent_material = {
        'provider_id': provider_id,
        'model_id': model_id,
        'data_sensitivity': sensitivity,
        'input_bytes': input_bytes,
        'requested_output_tokens': requested_output_tokens,
        'idempotency_key': idempotency_key,
        'input_digest': input_digest,
        'connection_id': connection_id,
        'provider_descriptor_ref': descriptor['descriptor_ref'],
        'hub_ref': HUB_GOVERNANCE_REF,
        'connect_ref': CONNECT_GOVERNED_REF,
    }

    return {
        'schema_version': PHASE5_GOVERNED_EXECUTION_SCHEMA,
        'execution_status': 'EXECUTION_NOT_AUTHORIZED',
        'readiness': 'BLOCKED_UPSTREAM_CAPABILITY_GAP',
        'intent_digest': _intent_digest(intent_material),
        'provider': provider_id,
        'model': model_id,
        'risk_class': descriptor['risk_class'],
        'selection_status': selection['selection_status'],
        'data_sensitivity': sensitivity,
        'input_bytes': input_bytes,
        'requested_output_tokens': requested_output_tokens,
        'input_digest': input_digest,
        'idempotency_key': idempotency_key,
        'connection_id': connection_id,
        'connection_binding_status': 'OPAQUE_ID_ACCEPTED_NOT_RESOLVED' if connection_id else 'NOT_BOUND',
        'provider_limits': {
            'allowed_sensitivity': list(descriptor['allowed_sensitivity']),
            'blocked_sensitivity': list(descriptor['blocked_sensitivity']),
            'max_input_bytes': descriptor['max_input_bytes'],
            'max_output_tokens': descriptor['max_output_tokens'],
        },
        'hub_authority': {
            'repository': HUB_GOVERNANCE_REPOSITORY,
            'ref': HUB_GOVERNANCE_REF,
            'policy_path': HUB_AUTHORITY_POLICY_PATH,
            'mode': HUB_AUTHORITY_MODE,
            'execution_enabled': HUB_EXECUTION_ENABLED,
            'risk_decision': HUB_R1_DECISION if descriptor['risk_class'] == 'R1' else None,
            'agent_allowed_subject_modes': list(HUB_AGENT_ALLOWED_SUBJECT_MODES),
        },
        'connect_boundary': {
            'repository': CONNECT_GOVERNED_REPOSITORY,
            'ref': CONNECT_GOVERNED_REF,
            'model_path': CONNECT_MODEL_PATH,
            'governed_executor_path': CONNECT_GOVERNED_EXECUTOR_PATH,
            'vault_boundary_path': CONNECT_VAULT_BOUNDARY_PATH,
            'current_action_modes': list(CONNECT_ACTION_MODES),
            'current_risk_classes': list(CONNECT_RISK_CLASSES),
            'credential_handle_prefix': CONNECT_CREDENTIAL_HANDLE_PREFIX,
            'raw_credential_exposure_allowed': False,
            'credential_resolution_performed': False,
        },
        'blockers': blockers,
        'automatic_routing_allowed': False,
        'silent_fallback_allowed': False,
        'fallback_performed': False,
        'credential_resolution_performed': False,
        'hub_authorization_performed': False,
        'network_call_performed': False,
        'provider_dispatch_performed': False,
        'next_gate': 'HUB_R1_EXECUTION_AUTHORITY_AND_CONNECT_R1_MODEL_API_EXECUTOR',
    }
