from __future__ import annotations

"""Tests for Q8.1's shadow telemetry module.

Covers, in order of how the module is meant to be trusted:
  1. the pure record-building helper (no I/O, easiest to get exactly right)
  2. the append-only writer in isolation (I/O, but still pure-ish: one
     record in, one JSON line out)
  3. the "never raises" invariant under a forced write failure -- this is
     the property the whole design leans on, so it gets its own explicit
     test rather than being assumed
  4. a real /api/chat round trip, proving the module is actually wired in
     and does not alter the existing response shape or behaviour
"""

import json

import pytest
from fastapi.testclient import TestClient

from services.api.app.config import settings
from services.api.app.efficiency_router_telemetry import (
    build_chat_telemetry_record,
    record_chat_telemetry,
    telemetry_log_path,
)
from services.api.app.main import app

client = TestClient(app)


def _read_lines() -> list[dict]:
    path = telemetry_log_path()
    if not path.exists():
        return []
    with path.open('r', encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def create_demo_project() -> dict:
    demo_path = str(settings.workspace_root / 'demo')
    for project in client.get('/api/projects').json():
        if project['name'] == 'Demo' and project['path'] == demo_path:
            return project
    response = client.post('/api/projects', json={'name': 'Demo', 'path': demo_path})
    return response.json()


def test_build_chat_telemetry_record_with_no_usage() -> None:
    """Local (Ollama/mock) calls have no usage object -- every numeric
    field must come back None, never 0, so an unmeasured cost is never
    confused with a measured-and-free one."""
    record = build_chat_telemetry_record(
        request_id='req-1',
        timestamp='2026-08-19T00:00:00+00:00',
        task='general',
        selection_mode='heuristic',
        provider_used='mock',
        model_used='mock-default',
        selection_reason='Mock mode was explicitly selected.',
        latency_ms=12,
        outcome='success',
    )
    assert record.prompt_tokens is None
    assert record.completion_tokens is None
    assert record.total_tokens is None
    assert record.cost_usd is None
    assert record.error_class is None
    assert record.outcome == 'success'


def test_build_chat_telemetry_record_extracts_openrouter_usage() -> None:
    """Usage extraction must match the exact shape InMyConnect's real
    governed receipt uses (promptTokens/completionTokens/totalTokens/cost)
    -- see docs/phase5-q6-bounded-e2e-acceptance-v1.md for the real example
    this shape is taken from."""
    usage = {
        'promptTokens': 38,
        'completionTokens': 28,
        'totalTokens': 66,
        'reasoningTokens': 26,
        'cachedTokens': 0,
        'cost': 0.0001335,
    }
    record = build_chat_telemetry_record(
        request_id='req-2',
        timestamp='2026-08-19T00:00:01+00:00',
        task='general',
        selection_mode='manual',
        provider_used='openrouter',
        model_used='google/gemini-3.7-flash',
        selection_reason='Explicit manual OpenRouter selection through Hub-governed InMyConnect; automatic routing and fallback are disabled.',
        latency_ms=812,
        outcome='success',
        usage=usage,
    )
    assert record.prompt_tokens == 38
    assert record.completion_tokens == 28
    assert record.total_tokens == 66
    assert record.cost_usd == 0.0001335


def test_build_chat_telemetry_record_ignores_malformed_usage() -> None:
    """A non-dict usage value must not raise -- it degrades to "no usage
    known", not a crash."""
    record = build_chat_telemetry_record(
        request_id='req-3',
        timestamp='2026-08-19T00:00:02+00:00',
        task='general',
        selection_mode='heuristic',
        provider_used='ollama',
        model_used='gemma3:4b',
        selection_reason='A generative task was detected and local Ollama is available.',
        latency_ms=400,
        outcome='success',
        usage='not-a-dict',  # type: ignore[arg-type]
    )
    assert record.prompt_tokens is None
    assert record.cost_usd is None


def test_record_chat_telemetry_appends_one_json_line() -> None:
    before = len(_read_lines())
    record = build_chat_telemetry_record(
        request_id='req-append-test',
        timestamp='2026-08-19T00:00:03+00:00',
        task='coding',
        selection_mode='heuristic',
        provider_used='ollama',
        model_used='qwen2.5-coder:3b',
        selection_reason='A generative task was detected and local Ollama is available.',
        latency_ms=250,
        outcome='success',
    )
    record_chat_telemetry(record)
    after = _read_lines()
    assert len(after) == before + 1
    last = after[-1]
    assert last['request_id'] == 'req-append-test'
    assert last['task_classification'] == 'coding'
    assert last['provider_used'] == 'ollama'
    assert last['outcome'] == 'success'
    # sanity: this is a plain observational log, not a governance record --
    # it must not accidentally grow fields that imply authority/spend truth.
    assert set(last.keys()) == {
        'request_id', 'timestamp', 'task_classification', 'selection_mode',
        'provider_used', 'model_used', 'selection_reason', 'latency_ms',
        'outcome', 'error_class', 'prompt_tokens', 'completion_tokens',
        'total_tokens', 'cost_usd',
    }


def test_record_chat_telemetry_never_raises_on_write_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """The single most important property of this module: a telemetry
    write failure must be fully swallowed. Forced here by pointing the
    log path at a location whose parent cannot be created (a path that
    is itself an existing FILE, so mkdir(parents=True) must fail with
    NotADirectoryError/FileExistsError)."""
    blocking_file = settings.data_dir / 'telemetry-blocker'
    blocking_file.parent.mkdir(parents=True, exist_ok=True)
    blocking_file.write_text('not a directory', encoding='utf-8')

    def _broken_path():
        return blocking_file / 'nested' / 'efficiency-router-shadow.jsonl'

    monkeypatch.setattr(
        'services.api.app.efficiency_router_telemetry.telemetry_log_path',
        _broken_path,
    )
    record = build_chat_telemetry_record(
        request_id='req-should-not-raise',
        timestamp='2026-08-19T00:00:04+00:00',
        task='general',
        selection_mode='heuristic',
        provider_used='mock',
        model_used='mock-default',
        selection_reason='Mock mode was explicitly selected.',
        latency_ms=5,
        outcome='success',
    )
    # Must not raise. If this test fails with an exception rather than an
    # assertion failure, the "never raises" invariant itself is broken.
    record_chat_telemetry(record)


def test_chat_writes_telemetry_without_changing_response_shape() -> None:
    """Wiring check: a normal mock chat call must still return exactly
    what it did before this module existed, AND must append a matching
    telemetry line. Neither property is optional -- Q8.1 must be
    additive-only."""
    project = create_demo_project()
    client.post(f"/api/projects/{project['id']}/index")
    before = len(_read_lines())
    response = client.post('/api/chat', json={
        'project_id': project['id'], 'message': 'What database does this project use?', 'provider': 'mock'
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['provider'] == 'mock'
    assert body['conversation_id'] > 0
    assert body['citations']

    after = _read_lines()
    assert len(after) == before + 1, 'exactly one telemetry line must be appended per chat request'
    last = after[-1]
    assert last['provider_used'] == 'mock'
    assert last['selection_mode'] == 'manual'  # provider was explicitly 'mock', not 'auto'
    assert last['outcome'] == 'success'
    assert last['error_class'] is None
    assert isinstance(last['latency_ms'], int)
    assert last['latency_ms'] >= 0
    # local/mock calls carry no token usage -- must stay None, not 0.
    assert last['prompt_tokens'] is None
    assert last['cost_usd'] is None


def test_chat_failure_path_still_records_telemetry_with_error_outcome() -> None:
    """An OpenRouter request missing required fields fails fast with a 400
    (existing behaviour, unchanged) -- Q8.1 must still record that this
    happened, with outcome='error', not silently skip failed requests."""
    project = create_demo_project()
    before = len(_read_lines())
    response = client.post('/api/chat', json={
        'project_id': project['id'],
        'message': 'hello',
        'provider': 'openrouter',
        # deliberately omitting connection_id/model/idempotency_key
    })
    assert response.status_code == 400

    after = _read_lines()
    assert len(after) == before + 1
    last = after[-1]
    assert last['provider_used'] == 'openrouter'
    assert last['outcome'] == 'error'
    assert last['error_class'] == 'HTTPException'
