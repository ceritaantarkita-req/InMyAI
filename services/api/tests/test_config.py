"""Regression test for the INMYAI_* env-prefix binding bug.

Before this fix, `Settings` had no `env_prefix` configured, so pydantic-settings
only ever bound bare env var names (PROVIDER, ALLOWED_ROOTS, ...) even though
.env.example and the README document INMYAI_-prefixed overrides
(INMYAI_PROVIDER, INMYAI_ALLOWED_ROOTS, INMYAI_DATA_DIR, ...). Every documented
INMYAI_* override silently had no effect. Ollama/ComfyUI vars are the
documented exception - .env.example intentionally keeps those bare
(OLLAMA_BASE_URL, OLLAMA_MODEL, COMFYUI_BASE_URL, COMFYUI_WORKFLOW_PATH) - so
this test also confirms those still bind unprefixed and that an INMYAI_-prefixed
variant of one of them is correctly ignored.

This test builds a fresh `Settings()` instance directly (bypassing the
shared, already-constructed `settings` singleton the rest of the app imports)
so it can control the environment precisely without disturbing other tests.
"""
from __future__ import annotations

import os

import pytest

from services.api.app.config import Settings

_ENV_KEYS = (
    'INMYAI_PROVIDER', 'INMYAI_ALLOWED_ROOTS', 'INMYAI_MAX_FILE_MB',
    'OLLAMA_BASE_URL', 'OLLAMA_MODEL', 'INMYAI_OLLAMA_BASE_URL',
)


@pytest.fixture(autouse=True)
def _clean_env():
    saved = {key: os.environ.get(key) for key in _ENV_KEYS}
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def test_inmyai_prefixed_vars_bind():
    os.environ['INMYAI_PROVIDER'] = 'ollama'
    os.environ['INMYAI_ALLOWED_ROOTS'] = '/tmp/allowed'
    os.environ['INMYAI_MAX_FILE_MB'] = '42'
    fresh = Settings(_env_file=None)
    assert fresh.provider == 'ollama'
    assert fresh.allowed_roots == '/tmp/allowed'
    assert fresh.max_file_mb == 42


def test_ollama_and_comfyui_vars_stay_unprefixed():
    os.environ['OLLAMA_BASE_URL'] = 'http://custom-host:1111'
    os.environ['OLLAMA_MODEL'] = 'qwen2.5-coder:3b'
    fresh = Settings(_env_file=None)
    assert fresh.ollama_base_url == 'http://custom-host:1111'
    assert fresh.ollama_model == 'qwen2.5-coder:3b'


def test_inmyai_prefixed_ollama_variant_is_ignored():
    # OLLAMA_BASE_URL uses an explicit validation_alias, so env_prefix must not
    # apply to it - an INMYAI_OLLAMA_BASE_URL variant should have no effect.
    os.environ['INMYAI_OLLAMA_BASE_URL'] = 'http://should-not-bind:9999'
    fresh = Settings(_env_file=None)
    assert fresh.ollama_base_url == 'http://127.0.0.1:11434'
