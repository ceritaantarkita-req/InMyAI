"""Q11.3 Piece 3: tests for the governed POST /api/scenarios/{slug}/run and
/replay endpoints, corrected to match this repo's real test convention
(confirmed against the full, real content of
services/api/tests/test_rnd_run_endpoint.py this session): absolute
imports, a module-level `TestClient(main.app)`, and stub client classes
installed via `monkeypatch.setattr(main, ...)` -- HTTP-level assertions via
`client.post(...)`, not direct calls to the route coroutines.

Belongs at services/api/tests/test_scenario_run_endpoint.py, mirroring
test_rnd_run_endpoint.py's own name and shape exactly. Supersedes the
earlier, wrongly-placed/wrongly-styled
services/api/app/test_scenario_execution_wiring.py (same test coverage,
rewritten for the real convention rather than a scaffold-only guess).

scenario_runtime's own execution behavior already has its dedicated Piece 1
test suite (services/api/tests/test_scenario_runtime.py) -- these tests
monkeypatch scenario_runtime's functions to isolate the governance wiring
(authorize -> intent -> local call -> receipt -> record) in main.py itself,
the same separation of concerns test_rnd_run_endpoint.py already draws
between rnd_run()'s wiring and InMyR&D's own execution.
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from services.api.app import main
from services.api.app import scenario_runtime
from services.api.app.connect_scenariohub import ScenarioExecutionError

client = TestClient(main.app)

SLUG = 'q11-3-context-recall-v1'
AUTH_ID = 'scenauth_' + 'a' * 40
INTENT_ID = 'scenhubi_' + 'b' * 40
HUB_RECEIPT_ID = 'scenhubr_' + 'c' * 40

VALID_PAYLOAD = {'idempotency_key': 'idem-run-endpoint-0001'}

RECEIPT_FIELDS = {
    'schemaVersion', 'receiptId', 'authorizationId', 'providerId', 'actionId',
    'scenarioSlug', 'scenarioVersion', 'scenarioDigest', 'mode', 'riskClass',
    'idempotencyKey', 'executedAt', 'outcome', 'outputs',
}


def _scenario_row(**overrides: Any) -> dict:
    script = [{'step': 1, 'instruction': 'ok'}]
    row = {
        'id': 1,
        'slug': SLUG,
        'name': 'Context recall',
        'version': 1,
        'description': 'test fixture',
        'script_json': json.dumps(script, sort_keys=True, separators=(',', ':'), ensure_ascii=False),
        'created_at': '2026-09-04T00:00:00.000Z',
    }
    row.update(overrides)
    return row


def _completed_run(**overrides: Any) -> dict:
    run = {
        'id': 1,
        'scenario_id': 1,
        'fixture_project_id': 900,
        'status': 'completed',
        'task_ids_json': json.dumps([101, 102, 103]),
        'trace_json': '[]',
        'trace_hash': 'a' * 64,
        'error': None,
        'created_at': '2026-09-04T00:00:00.000Z',
        'completed_at': '2026-09-04T00:00:05.000Z',
        'replay_of_run_id': None,
        'replay_match': None,
    }
    run.update(overrides)
    return run


class StubScenarioAuthorityClient:
    """Mirrors test_rnd_run_endpoint.py's real StubRndAuthorityClient shape:
    an injectable stand-in for ScenarioAuthorityClient, installed via
    `monkeypatch.setattr(main, '_scenario_authority_client', lambda: ...)`,
    call-tracking lists so tests can assert both call *count* (e.g. "record
    must never be called after an intent failure") and call *content* (the
    executor receipt actually sent).
    """

    def __init__(
        self,
        *,
        authorization_id: str = AUTH_ID,
        fail_at: str | None = None,
        fail_exc: Exception | None = None,
    ) -> None:
        self.authorization_id = authorization_id
        self.fail_at = fail_at
        self.fail_exc = fail_exc
        self.authorize_calls: list[dict] = []
        self.record_intent_calls: list[dict] = []
        self.record_execution_calls: list[dict] = []

    async def authorize(self, **kwargs: Any) -> dict:
        self.authorize_calls.append(kwargs)
        if self.fail_at == 'authorize':
            raise self.fail_exc
        return {'authorizationId': self.authorization_id, 'expiresAt': '2026-09-04T00:05:00.000Z'}

    async def record_intent(self, **kwargs: Any) -> dict:
        self.record_intent_calls.append(kwargs)
        if self.fail_at == 'record_intent':
            raise self.fail_exc
        return {'intentId': INTENT_ID}

    async def record_execution(self, **kwargs: Any) -> dict:
        self.record_execution_calls.append(kwargs)
        if self.fail_at == 'record_execution':
            raise self.fail_exc
        return {
            'receiptId': HUB_RECEIPT_ID,
            'authorizationId': self.authorization_id,
            'outcome': kwargs['executor_receipt']['outcome'],
        }


def _patch_authority(monkeypatch: pytest.MonkeyPatch, authority: StubScenarioAuthorityClient) -> None:
    monkeypatch.setattr(main, '_scenario_authority_client', lambda: authority)


def test_run_scenario_happy_path_builds_correct_receipt(monkeypatch):
    monkeypatch.setattr(scenario_runtime, 'get_scenario', lambda slug: _scenario_row())

    async def fake_run_scenario(slug):
        return _completed_run()
    monkeypatch.setattr(scenario_runtime, 'run_scenario', fake_run_scenario)

    authority = StubScenarioAuthorityClient()
    _patch_authority(monkeypatch, authority)

    response = client.post(f'/api/scenarios/{SLUG}/run', json=VALID_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert body['authorizationId'] == AUTH_ID
    assert body['hubReceiptId'] == HUB_RECEIPT_ID
    assert body['run']['status'] == 'completed'

    assert len(authority.authorize_calls) == 1
    assert len(authority.record_intent_calls) == 1
    assert len(authority.record_execution_calls) == 1

    receipt = authority.record_execution_calls[0]['executor_receipt']
    assert set(receipt.keys()) == RECEIPT_FIELDS
    assert receipt['providerId'] == 'inmyai-scenario'
    assert receipt['actionId'] == 'scenario.run'
    assert receipt['mode'] == 'scenario-execution'
    assert receipt['riskClass'] == 'R1'
    assert receipt['outcome'] == 'completed'
    assert receipt['scenarioSlug'] == SLUG
    assert receipt['scenarioVersion'] == 1
    assert receipt['scenarioDigest'].startswith('sha256:')
    # the load-bearing prefixing check: scenario_runtime.py's trace_hash
    # column is unprefixed 64-hex; an unprefixed value sent to Hub is
    # silently normalized to null rather than erroring.
    assert receipt['outputs']['traceHash'] == 'sha256:' + 'a' * 64
    assert receipt['outputs']['stepCount'] == 3
    assert receipt['outputs']['replayOfTraceHash'] is None
    assert receipt['outputs']['replayMatch'] is None


def test_replay_scenario_prefixes_baseline_trace_hash(monkeypatch):
    baseline = _completed_run(id=1, trace_hash='a' * 64)
    replay_run = _completed_run(id=2, trace_hash='b' * 64, replay_of_run_id=1, replay_match=False)

    monkeypatch.setattr(scenario_runtime, 'get_scenario', lambda slug: _scenario_row())

    async def fake_replay_scenario(slug, against_run_id):
        return replay_run
    monkeypatch.setattr(scenario_runtime, 'replay_scenario', fake_replay_scenario)

    def fake_scenario_run_detail(run_id):
        if run_id == 1:
            return baseline
        raise KeyError(run_id)
    monkeypatch.setattr(scenario_runtime, 'scenario_run_detail', fake_scenario_run_detail)

    authority = StubScenarioAuthorityClient()
    _patch_authority(monkeypatch, authority)

    response = client.post(f'/api/scenarios/{SLUG}/replay', params={'against_run_id': 1}, json=VALID_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert body['run']['id'] == 2

    receipt = authority.record_execution_calls[0]['executor_receipt']
    assert receipt['outputs']['traceHash'] == 'sha256:' + 'b' * 64
    assert receipt['outputs']['replayOfTraceHash'] == 'sha256:' + 'a' * 64
    assert receipt['outputs']['replayMatch'] is False


def test_run_scenario_unknown_slug_returns_404_and_makes_no_hub_call(monkeypatch):
    def missing(slug):
        raise KeyError(f'Scenario {slug!r} was not found.')
    monkeypatch.setattr(scenario_runtime, 'get_scenario', missing)

    authority = StubScenarioAuthorityClient()
    _patch_authority(monkeypatch, authority)

    response = client.post('/api/scenarios/does-not-exist/run', json=VALID_PAYLOAD)

    assert response.status_code == 404
    assert authority.authorize_calls == []


def test_run_scenario_local_execution_failure_returns_400_and_records_no_receipt(monkeypatch):
    monkeypatch.setattr(scenario_runtime, 'get_scenario', lambda slug: _scenario_row())

    async def fake_run_scenario(slug):
        raise RuntimeError('boom')
    monkeypatch.setattr(scenario_runtime, 'run_scenario', fake_run_scenario)

    authority = StubScenarioAuthorityClient()
    _patch_authority(monkeypatch, authority)

    response = client.post(f'/api/scenarios/{SLUG}/run', json=VALID_PAYLOAD)

    assert response.status_code == 400
    # authorize + intent already happened (mirrors rnd_run()'s own
    # precedent for this exact shape) -- only record_execution is skipped.
    assert len(authority.authorize_calls) == 1
    assert len(authority.record_intent_calls) == 1
    assert authority.record_execution_calls == []


def test_run_scenario_authorize_denial_surfaces_as_matching_status(monkeypatch):
    monkeypatch.setattr(scenario_runtime, 'get_scenario', lambda slug: _scenario_row())

    authority = StubScenarioAuthorityClient(
        fail_at='authorize',
        fail_exc=ScenarioExecutionError(
            'denied', status_code=409, code='R1_SCENARIO_AUTHORIZATION_REPLAY_MISMATCH',
        ),
    )
    _patch_authority(monkeypatch, authority)

    response = client.post(f'/api/scenarios/{SLUG}/run', json=VALID_PAYLOAD)

    assert response.status_code == 409


def test_run_scenario_intent_failure_stops_before_local_execution(monkeypatch):
    monkeypatch.setattr(scenario_runtime, 'get_scenario', lambda slug: _scenario_row())

    calls: list[str] = []

    async def fake_run_scenario(slug):
        calls.append(slug)
        return _completed_run()
    monkeypatch.setattr(scenario_runtime, 'run_scenario', fake_run_scenario)

    authority = StubScenarioAuthorityClient(
        fail_at='record_intent',
        fail_exc=ScenarioExecutionError('unavailable', status_code=503, code='R1_SCENARIO_AUTHORITY_UNAVAILABLE'),
    )
    _patch_authority(monkeypatch, authority)

    response = client.post(f'/api/scenarios/{SLUG}/run', json=VALID_PAYLOAD)

    assert response.status_code == 503
    assert calls == []


def test_run_scenario_hub_record_failure_after_real_execution_is_a_distinct_502(monkeypatch):
    # Mirrors rnd_run()'s own real handling of this exact shape: the local
    # scenario_runtime execution already happened for real by this point --
    # do not claim success, but also do not report this the same way as an
    # authorize/intent denial.
    monkeypatch.setattr(scenario_runtime, 'get_scenario', lambda slug: _scenario_row())

    async def fake_run_scenario(slug):
        return _completed_run()
    monkeypatch.setattr(scenario_runtime, 'run_scenario', fake_run_scenario)

    authority = StubScenarioAuthorityClient(
        fail_at='record_execution',
        fail_exc=ScenarioExecutionError('unavailable', status_code=503, code='R1_SCENARIO_AUTHORITY_UNAVAILABLE'),
    )
    _patch_authority(monkeypatch, authority)

    response = client.post(f'/api/scenarios/{SLUG}/run', json=VALID_PAYLOAD)

    assert response.status_code == 502
    assert 'recording it to InMyHub failed' in response.json()['detail']


def test_run_scenario_requires_an_idempotency_key(monkeypatch):
    monkeypatch.setattr(scenario_runtime, 'get_scenario', lambda slug: _scenario_row())
    authority = StubScenarioAuthorityClient()
    _patch_authority(monkeypatch, authority)

    response = client.post(f'/api/scenarios/{SLUG}/run', json={})

    assert response.status_code == 422
    assert authority.authorize_calls == []


def test_replay_scenario_requires_an_idempotency_key(monkeypatch):
    monkeypatch.setattr(scenario_runtime, 'get_scenario', lambda slug: _scenario_row())
    authority = StubScenarioAuthorityClient()
    _patch_authority(monkeypatch, authority)

    response = client.post(f'/api/scenarios/{SLUG}/replay', json={})

    assert response.status_code == 422
    assert authority.authorize_calls == []


def test_run_scenario_rejects_a_malformed_idempotency_key(monkeypatch):
    monkeypatch.setattr(scenario_runtime, 'get_scenario', lambda slug: _scenario_row())
    authority = StubScenarioAuthorityClient()
    _patch_authority(monkeypatch, authority)

    response = client.post(f'/api/scenarios/{SLUG}/run', json={'idempotency_key': 'short'})

    assert response.status_code == 422
    assert authority.authorize_calls == []
