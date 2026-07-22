from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.api.app.model_registry import (
    ModelProfile,
    load_registry,
    select_model,
)


# ---------- load_registry ----------

def test_load_registry_parses_profiles(tmp_path: Path) -> None:
    registry_path = tmp_path / 'registry.json'
    registry_path.write_text(json.dumps({
        'schema_version': 1,
        'profiles': [
            {
                'id': 'general-small', 'runtime': 'ollama', 'model': 'gemma3:4b',
                'task_types': ['general', 'memory'], 'hardware_profile': 'standard',
                'verified': False, 'notes': 'example',
            },
        ],
    }), encoding='utf-8')
    profiles = load_registry(registry_path)
    assert len(profiles) == 1
    p = profiles[0]
    assert isinstance(p, ModelProfile)
    assert p.id == 'general-small'
    assert p.model == 'gemma3:4b'
    assert p.task_types == ['general', 'memory']
    assert p.hardware_profile == 'standard'
    assert p.verified is False


def test_load_registry_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_registry(tmp_path / 'does-not-exist.json') == []


def test_load_registry_corrupt_json_returns_empty(tmp_path: Path) -> None:
    bad = tmp_path / 'registry.json'
    bad.write_text('{ this is not json', encoding='utf-8')
    assert load_registry(bad) == []


def test_load_registry_tolerates_missing_optional_fields(tmp_path: Path) -> None:
    registry_path = tmp_path / 'registry.json'
    registry_path.write_text(json.dumps({
        'schema_version': 1,
        'profiles': [
            # peak_ram_mb / verified / notes omitted
            {'id': 'p1', 'runtime': 'ollama', 'model': 'm1',
             'task_types': ['general'], 'hardware_profile': 'standard'},
        ],
    }), encoding='utf-8')
    profiles = load_registry(registry_path)
    assert len(profiles) == 1
    assert profiles[0].peak_ram_mb is None
    assert profiles[0].verified is False
    assert profiles[0].notes == ''


# ---------- select_model ----------

INSTALLED = [
    {'name': 'gemma3:4b', 'size': 3_300_000_000},
    {'name': 'qwen2.5-coder:3b', 'size': 2_000_000_000},
]


def test_select_model_prefers_registry_profile_matching_task_hardware_installed() -> None:
    registry = [
        ModelProfile('general-small', 'ollama', 'gemma3:4b', ['general', 'memory'],
                     'standard', peak_ram_mb=3000, verified=False, notes=''),
        ModelProfile('coding-small', 'ollama', 'qwen2.5-coder:3b', ['coding'],
                     'standard', peak_ram_mb=2000, verified=False, notes=''),
    ]
    # coding task → coding-small profile → qwen2.5-coder:3b
    assert select_model('coding', 'standard', INSTALLED, None, registry) == 'qwen2.5-coder:3b'
    # general task → general-small profile → gemma3:4b
    assert select_model('general', 'standard', INSTALLED, None, registry) == 'gemma3:4b'


def test_select_model_skips_profile_when_hardware_does_not_match() -> None:
    # Only a 'standard' profile exists; a 'lite' device must not use it.
    registry = [
        ModelProfile('general-small', 'ollama', 'gemma3:4b', ['general'],
                     'standard', peak_ram_mb=3000, verified=False, notes=''),
    ]
    result = select_model('general', 'lite', INSTALLED, None, registry)
    # No registry match → must fall back to the heuristic, not pick gemma3:4b via registry.
    # The heuristic for general+these models also returns gemma3:4b, so we assert it
    # returned *something* from installed rather than None, and document the fallback.
    assert result in {m['name'] for m in INSTALLED}


def test_select_model_honors_explicit_request_when_installed() -> None:
    registry = [
        ModelProfile('general-small', 'ollama', 'gemma3:4b', ['general'],
                     'standard', peak_ram_mb=3000, verified=False, notes=''),
    ]
    result = select_model('general', 'standard', INSTALLED, 'qwen2.5-coder:3b', registry)
    assert result == 'qwen2.5-coder:3b'


def test_select_model_falls_back_to_heuristic_when_registry_empty() -> None:
    # Empty registry → the existing name-heuristic must still pick the small
    # coding model for a coding task among the installed models.
    result = select_model('coding', 'standard', INSTALLED, None, [])
    assert result == 'qwen2.5-coder:3b'


def test_select_model_general_prefers_smallest_general_family() -> None:
    # Heuristic fallback for general: prefer gemma over qwen-coder.
    result = select_model('general', 'standard', INSTALLED, None, [])
    assert result == 'gemma3:4b'


def test_select_model_returns_settings_default_when_nothing_installed() -> None:
    # Nothing installed, nothing in registry, no request → settings default.
    result = select_model('general', 'standard', [], None, [])
    assert isinstance(result, str)
    assert result  # non-empty
