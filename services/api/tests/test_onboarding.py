"""Ollama onboarding: model recommendation + phase detection.

The wizard needs (a) model recommendations matched to the device's hardware
profile, and (b) a single phase string telling the UI which step to show
(download / start / pull / ready). These tests cover the pure recommendation
logic and the endpoint's phase classification (with the install/running state
monkeypatched so the tests don't depend on a real Ollama).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from services.api.app.main import app
from services.api.app.model_registry import ModelProfile, recommend_for_hardware

client = TestClient(app)


# ---------- recommend_for_hardware (pure) ----------

def test_recommend_for_hardware_lite_returns_lite_profiles() -> None:
    recs = recommend_for_hardware('lite')
    assert recs, 'expected at least one lite recommendation'
    assert all(p.hardware_profile == 'lite' for p in recs), (
        [p.id for p in recs]
    )
    models = {p.model for p in recs}
    # The shipped registry has lite profiles for these two.
    assert 'gemma3:1b' in models
    assert 'qwen2.5-coder:1.5b' in models


def test_recommend_for_hardware_standard_returns_standard_profiles() -> None:
    recs = recommend_for_hardware('standard')
    assert recs
    assert all(p.hardware_profile == 'standard' for p in recs)
    models = {p.model for p in recs}
    assert 'gemma3:4b' in models
    assert 'qwen2.5-coder:3b' in models


def test_recommend_for_hardware_lite_excludes_standard() -> None:
    recs = recommend_for_hardware('lite')
    models = {p.model for p in recs}
    # The heavier standard-only models must NOT be recommended for lite.
    assert 'gemma3:4b' not in models
    assert 'qwen2.5-coder:3b' not in models


def test_recommend_for_hardware_unknown_profile_returns_empty() -> None:
    assert recommend_for_hardware('ultra') == []


def test_recommend_includes_coding_and_general() -> None:
    recs = recommend_for_hardware('lite')
    tasks = {t for p in recs for t in p.task_types}
    assert 'coding' in tasks
    assert 'general' in tasks


# ---------- endpoint phase classification ----------

@pytest.fixture
def patch_install_state(monkeypatch):
    """Allow a test to force the install/running/models state seen by the endpoint.

    The endpoint imported get_ollama_install_state by name into main, so patch
    the binding in the main module (not providers) for it to take effect.
    """
    def _patch(*, installed: bool, running: bool, models: list[dict], version: str | None = '0.1.0'):
        async def _fake():
            return {
                'installed': installed, 'version': version,
                'running': running, 'models': models, 'base_url': 'http://127.0.0.1:11434',
            }
        from services.api.app import main as main_module
        monkeypatch.setattr(main_module, 'get_ollama_install_state', _fake)
    return _patch


def test_endpoint_phase_download_when_not_installed(patch_install_state) -> None:
    patch_install_state(installed=False, running=False, models=[])
    body = client.get('/api/models/onboarding').json()
    assert body['phase'] == 'download_ollama'
    assert body['installed'] is False
    assert body['recommended'], 'recommendations should still be present for guidance'


def test_endpoint_phase_start_when_installed_but_not_running(patch_install_state) -> None:
    patch_install_state(installed=True, running=False, models=[])
    body = client.get('/api/models/onboarding').json()
    assert body['phase'] == 'start_ollama'
    assert body['installed'] is True


def test_endpoint_phase_pull_when_running_without_models(patch_install_state) -> None:
    patch_install_state(installed=True, running=True, models=[])
    body = client.get('/api/models/onboarding').json()
    assert body['phase'] == 'pull_model'


def test_endpoint_phase_ready_when_running_with_models(patch_install_state) -> None:
    patch_install_state(installed=True, running=True, models=[{'name': 'gemma3:1b'}])
    body = client.get('/api/models/onboarding').json()
    assert body['phase'] == 'ready'
    assert body['models'][0]['name'] == 'gemma3:1b'


def test_endpoint_recommended_items_include_pull_command(patch_install_state) -> None:
    patch_install_state(installed=False, running=False, models=[])
    body = client.get('/api/models/onboarding').json()
    for item in body['recommended']:
        assert item['pull_command'] == f"ollama pull {item['model']}", item


def test_endpoint_includes_hardware_profile(patch_install_state) -> None:
    patch_install_state(installed=True, running=True, models=[{'name': 'x'}])
    body = client.get('/api/models/onboarding').json()
    assert body['hardware_profile'] in ('lite', 'standard')
