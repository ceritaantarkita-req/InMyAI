from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any


PHASE5_PROVIDER_PORTABILITY_SCHEMA = '1.1.0'
CONNECT_PROVIDER_FOUNDATION_REPOSITORY = 'ceritaantarkita-req/InMyConnect'
CONNECT_PROVIDER_FOUNDATION_REF = '65d8be8692da237961dc19a76147bab8739c8597'
CONNECT_OPENROUTER_ADAPTER_PATH = 'src/providers/openrouter.mjs'
CONNECT_OPENROUTER_RUNTIME_PATH = 'src/connect-openrouter-governed-runtime.mjs'

_PROVIDER_ID = re.compile(r'^[a-z][a-z0-9-]{1,63}$')
_MODEL_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/~-]{0,191}$')


@dataclass(frozen=True)
class PortableProviderDescriptor:
    provider_id: str
    display_name: str
    transport: str
    connection_owner: str
    descriptor_repository: str
    descriptor_ref: str
    descriptor_path: str
    runtime_path: str
    execution_state: str
    risk_class: str
    selection_mode: str
    automatic_routing_allowed: bool
    dispatch_allowed: bool
    credential_resolution: str
    raw_credential_exposure_allowed: bool
    browser_session_credentials_allowed: bool
    model_discovery_state: str
    default_model: str | None
    allowed_sensitivity: tuple[str, ...]
    blocked_sensitivity: tuple[str, ...]
    max_input_bytes: int
    max_output_tokens: int


OPENROUTER = PortableProviderDescriptor(
    provider_id='openrouter',
    display_name='OpenRouter',
    transport='official-api-via-inmyconnect',
    connection_owner='InMyConnect',
    descriptor_repository=CONNECT_PROVIDER_FOUNDATION_REPOSITORY,
    descriptor_ref=CONNECT_PROVIDER_FOUNDATION_REF,
    descriptor_path=CONNECT_OPENROUTER_ADAPTER_PATH,
    runtime_path=CONNECT_OPENROUTER_RUNTIME_PATH,
    execution_state='hub-governed',
    risk_class='R1',
    selection_mode='manual-only',
    automatic_routing_allowed=False,
    dispatch_allowed=True,
    credential_resolution='INMYCONNECT_ONLY',
    raw_credential_exposure_allowed=False,
    browser_session_credentials_allowed=False,
    model_discovery_state='account-filtered-live-via-connect',
    default_model=None,
    allowed_sensitivity=('PUBLIC', 'INTERNAL'),
    blocked_sensitivity=('SENSITIVE', 'RESTRICTED'),
    max_input_bytes=262_144,
    max_output_tokens=8_192,
)

_PORTABLE_PROVIDERS = {
    OPENROUTER.provider_id: OPENROUTER,
}


def _bounded_identifier(value: str, regex: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f'{label} must be a string.')
    cleaned = value.strip()
    if cleaned != value or not regex.fullmatch(cleaned):
        raise ValueError(f'{label} is invalid.')
    return cleaned


def get_portable_provider_descriptor(provider_id: str) -> dict[str, Any]:
    provider = _bounded_identifier(provider_id, _PROVIDER_ID, 'provider_id')
    descriptor = _PORTABLE_PROVIDERS.get(provider)
    if descriptor is None:
        raise ValueError(f'Portable provider is not registered: {provider}.')
    return asdict(descriptor)


def list_portable_provider_catalog() -> list[dict[str, Any]]:
    """Return the explicit Phase 5 cloud-provider catalog.

    OpenRouter is the first real provider target. The catalog contains no API
    key, does not choose a model automatically, and does not authorize silent
    fallback. Execution still requires the local InMyConnect bridge and a Hub
    authorization for every R1 request.
    """

    return [get_portable_provider_descriptor(key) for key in sorted(_PORTABLE_PROVIDERS)]


def plan_manual_provider_selection(
    provider_id: str,
    model_id: str,
    *,
    selection_mode: str = 'manual',
) -> dict[str, Any]:
    provider = _bounded_identifier(provider_id, _PROVIDER_ID, 'provider_id')
    if selection_mode != 'manual':
        raise ValueError('Portable cloud provider selection must remain manual.')
    descriptor = _PORTABLE_PROVIDERS.get(provider)
    if descriptor is None:
        raise ValueError(f'Portable provider is not registered: {provider}.')
    model = _bounded_identifier(model_id, _MODEL_ID, 'model_id')

    if descriptor.selection_mode != 'manual-only':
        raise ValueError('Provider descriptor does not allow the required manual-only selection mode.')
    if descriptor.automatic_routing_allowed:
        raise ValueError('Provider descriptor unexpectedly permits automatic routing.')
    if descriptor.dispatch_allowed is not True:
        raise ValueError('Provider descriptor does not expose the governed execution path.')

    return {
        'schema_version': PHASE5_PROVIDER_PORTABILITY_SCHEMA,
        'provider': descriptor.provider_id,
        'model': model,
        'selection_mode': 'manual',
        'selection_status': 'SELECTED_GOVERNED_PATH',
        'descriptor': {
            'repository': descriptor.descriptor_repository,
            'ref': descriptor.descriptor_ref,
            'path': descriptor.descriptor_path,
            'runtime_path': descriptor.runtime_path,
        },
        'connection_owner': descriptor.connection_owner,
        'credential_resolution': descriptor.credential_resolution,
        'risk_class': descriptor.risk_class,
        'execution_state': descriptor.execution_state,
        'allowed_sensitivity': list(descriptor.allowed_sensitivity),
        'blocked_sensitivity': list(descriptor.blocked_sensitivity),
        'max_input_bytes': descriptor.max_input_bytes,
        'max_output_tokens': descriptor.max_output_tokens,
        'raw_credential_exposure_allowed': False,
        'browser_session_credentials_allowed': False,
        'automatic_routing_allowed': False,
        'dispatch_allowed': True,
        'network_call_performed': False,
        'next_gate': 'CONNECT_RUNTIME_AND_HUB_SERVICE_IDENTITY',
    }


def portable_provider_is_execution_authorized(provider_id: str) -> bool:
    """Return whether a provider may be dispatched only through the governed path."""

    provider = _bounded_identifier(provider_id, _PROVIDER_ID, 'provider_id')
    descriptor = _PORTABLE_PROVIDERS.get(provider)
    if descriptor is None:
        return False
    return descriptor.dispatch_allowed is True and descriptor.execution_state == 'hub-governed'
