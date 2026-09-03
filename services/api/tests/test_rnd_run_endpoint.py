from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from services.api.app import main
from services.api.app.connect_inmyrnd import RndExecutionError, experiment_digest


client = TestClient(main.app)

AUTH_ID = 'rndauth_' + ('a' * 20)
PROJECT_ID = 'rndp_22222222-2222-2222-2222-222222222222'
EXPERIMENT_ID = 'rnde_11111111-1111-1111-1111-111111111111'

VALID_PAYLOAD = {
    'project_id': PROJECT_ID,
    'experiment_id': EXPERIMENT_ID,
    'idempotency_key': 'rnd-run-endpoint-test-0001',
}

RECEIPT_FIELDS = {
    'schemaVersion', 'receiptId', 'authorizationId', 'providerId', 'actionId',
    'projectId', 'experimentId', 'experimentDigest', 'mode', 'riskClass',
    'idempotencyKey', 'executedAt', 'outcome', 'outputs',
}


def _experiment(**overrides: Any) -> dict[str, Any]:
    base = {
        'schemaVersion': 1,
        'id': EXPERIMENT_ID,
        'projectId': PROJECT_ID,
        'name': 'Baseline vs variant',
        'hypothesis': 'Variant B improves quality',
        'status': 'ready',
        'mode': 'deterministic-scorecard',
        'weights': {'quality': 0.35, 'cost': 0.2, 'latency': 0.15, 'privacy': 0.15, 'reliability': 0.15},
        'cases': [
            {
                'id': 'case_aaa', 'name': 'Baseline', 'evidenceClass': 'measured',
                'evidenceRef': 'https://example.com/report', 'notes': 'control group',
                'metrics': {'quality': 70, 'cost': 50, 'latency': 60, 'privacy': 80, 'reliability': 90},
            },
            {
                'id': 'case_bbb', 'name': 'Variant B', 'evidenceClass': 'assumption',
                'evidenceRef': '', 'notes': '',
                'metrics': {'quality': 85, 'cost': 40, 'latency': 55, 'privacy': 75, 'reliability': 88},
            },
        ],
        'createdAt': '2026-09-03T00:00:00.000Z',
        'updatedAt': '2026-09-03T00:00:00.000Z',
    }
    base.update(overrides)
    return base


def _run(experiment: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    base = {
        'schemaVersion': 1,
        'id': 'rndr_test',
        'experimentId': experiment['id'],
        'projectId': experiment['projectId'],
        'experimentDigest': experiment_digest(experiment),
        'algorithmVersion': 'deterministic-scorecard-v1',
        'mode': 'deterministic-scorecard',
        'weights': experiment['weights'],
        'evidenceSummary': {'measured': 1, 'simulated': 0, 'assumption': 1, 'inference': 0, 'unknown': 0, 'real_world': 0},
        'rows': [
            {'caseId': 'case_bbb', 'name': 'Variant B', 'evidenceClass': 'assumption', 'evidenceRef': '', 'score': 71.85, 'metrics': experiment['cases'][1]['metrics']},
            {'caseId': 'case_aaa', 'name': 'Baseline', 'evidenceClass': 'measured', 'evidenceRef': 'https://example.com/report', 'score': 69.5, 'metrics': experiment['cases'][0]['metrics']},
        ],
        'recommendation': {'caseId': 'case_bbb', 'name': 'Variant B', 'score': 71.85},
        'disclaimer': 'Scores are deterministic calculations over user-supplied evidence.',
        'createdAt': '2026-09-03T00:00:02.000Z',
    }
    base.update(overrides)
    return base


class StubRndAuthorityClient:
    def __init__(self, *, authorization_id: str = AUTH_ID, fail_at: str | None = None, fail_exc: Exception | None = None) -> None:
        self.authorization_id = authorization_id
        self.fail_at = fail_at
        self.fail_exc = fail_exc
        self.authorize_calls: list[dict[str, Any]] = []
        self.intent_calls: list[dict[str, Any]] = []
        self.record_calls: list[dict[str, Any]] = []

    async def authorize(self, **kwargs: Any) -> dict[str, Any]:
        self.authorize_calls.append(kwargs)
        if self.fail_at == 'authorize':
            raise self.fail_exc
        return {'authorizationId': self.authorization_id, 'expiresAt': '2026-09-03T00:06:00Z'}

    async def record_intent(self, **kwargs: Any) -> dict[str, Any]:
        self.intent_calls.append(kwargs)
        if self.fail_at == 'intent':
            raise self.fail_exc
        return {'authorizationId': self.authorization_id}

    async def record_execution(self, **kwargs: Any) -> dict[str, Any]:
        self.record_calls.append(kwargs)
        if self.fail_at == 'record':
            raise self.fail_exc
        return {
            'receiptId': 'rndhubr_test',
            'authorizationId': self.authorization_id,
            'outcome': kwargs['executor_receipt']['outcome'],
        }


class StubInMyRndRuntimeClient:
    def __init__(
        self, *, experiments: list[dict[str, Any]] | None = None, run: dict[str, Any] | None = None,
        fail_at: str | None = None, fail_exc: Exception | None = None,
    ) -> None:
        self.experiments = experiments if experiments is not None else [_experiment()]
        self.run_result = run if run is not None else (_run(self.experiments[0]) if self.experiments else None)
        self.fail_at = fail_at
        self.fail_exc = fail_exc
        self.list_calls = 0
        self.run_calls: list[str] = []

    async def list_experiments(self) -> list[dict[str, Any]]:
        self.list_calls += 1
        if self.fail_at == 'list':
            raise self.fail_exc
        return self.experiments

    async def run_experiment(self, experiment_id: str) -> dict[str, Any]:
        self.run_calls.append(experiment_id)
        if self.fail_at == 'run':
            raise self.fail_exc
        return self.run_result


def _patch(monkeypatch: pytest.MonkeyPatch, authority: StubRndAuthorityClient, runtime: StubInMyRndRuntimeClient) -> None:
    monkeypatch.setattr(main, '_rnd_authority_client', lambda: authority)
    monkeypatch.setattr(main, '_inmyrnd_runtime_client', lambda: runtime)


def test_rnd_run_happy_path_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    authority = StubRndAuthorityClient()
    runtime = StubInMyRndRuntimeClient()
    _patch(monkeypatch, authority, runtime)

    response = client.post('/api/rnd/run', json=VALID_PAYLOAD)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['outcome'] == 'completed'
    assert body['hubReceiptId'] == 'rndhubr_test'
    assert body['authorizationId'] == AUTH_ID
    assert body['recommendation']['caseId'] == 'case_bbb'
    assert len(body['rows']) == 2

    assert runtime.list_calls == 1
    assert runtime.run_calls == [EXPERIMENT_ID]
    assert len(authority.authorize_calls) == 1
    assert len(authority.intent_calls) == 1
    assert len(authority.record_calls) == 1
    assert authority.intent_calls[0]['authorization_id'] == AUTH_ID
    assert authority.record_calls[0]['authorization_id'] == AUTH_ID

    experiment = runtime.experiments[0]
    expected_digest = experiment_digest(experiment)
    assert authority.authorize_calls[0]['experiment_digest'] == expected_digest
    assert authority.authorize_calls[0]['project_id'] == PROJECT_ID
    assert authority.authorize_calls[0]['experiment_id'] == EXPERIMENT_ID

    receipt = authority.record_calls[0]['executor_receipt']
    assert set(receipt.keys()) == RECEIPT_FIELDS
    assert receipt['mode'] == 'rnd-execution'
    assert receipt['riskClass'] == 'R1'
    assert receipt['outcome'] == 'completed'
    assert receipt['experimentDigest'] == expected_digest
    assert receipt['idempotencyKey'] == VALID_PAYLOAD['idempotency_key']
    assert receipt['outputs']['recommendationCaseId'] == 'case_bbb'
    assert receipt['outputs']['recommendationScore'] == 71.85
    assert receipt['outputs']['rowCount'] == 2
    assert receipt['outputs']['algorithmVersion'] == 'deterministic-scorecard-v1'


def test_rnd_run_experiment_not_found_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    authority = StubRndAuthorityClient()
    runtime = StubInMyRndRuntimeClient(experiments=[])
    _patch(monkeypatch, authority, runtime)

    response = client.post('/api/rnd/run', json=VALID_PAYLOAD)
    assert response.status_code == 404, response.text
    assert authority.authorize_calls == []
    assert runtime.run_calls == []


def test_rnd_run_project_id_mismatch_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    # The experiment id exists but belongs to a different project -- must
    # not be treated as found. This is the local guard against a caller
    # asserting the wrong project_id/experiment_id pairing.
    authority = StubRndAuthorityClient()
    other_project = 'rndp_99999999-9999-9999-9999-999999999999'
    runtime = StubInMyRndRuntimeClient(experiments=[_experiment(projectId=other_project)])
    _patch(monkeypatch, authority, runtime)

    response = client.post('/api/rnd/run', json=VALID_PAYLOAD)
    assert response.status_code == 404, response.text
    assert authority.authorize_calls == []


def test_rnd_run_authorize_failure_stops_before_any_side_effect(monkeypatch: pytest.MonkeyPatch) -> None:
    exc = RndExecutionError('Hub unavailable', status_code=503, code='R1_RND_AUTHORITY_UNAVAILABLE', execution_may_have_run=False)
    authority = StubRndAuthorityClient(fail_at='authorize', fail_exc=exc)
    runtime = StubInMyRndRuntimeClient()
    _patch(monkeypatch, authority, runtime)

    response = client.post('/api/rnd/run', json=VALID_PAYLOAD)
    assert response.status_code == 503, response.text
    assert 'Hub unavailable' in response.text
    assert 'already been recorded' not in response.text
    assert authority.intent_calls == []
    assert authority.record_calls == []
    assert runtime.run_calls == []


def test_rnd_run_intent_failure_stops_before_run_experiment(monkeypatch: pytest.MonkeyPatch) -> None:
    exc = RndExecutionError('bad intent', status_code=400, code='R1_RND_EXECUTION_INTENT_INVALID', execution_may_have_run=False)
    authority = StubRndAuthorityClient(fail_at='intent', fail_exc=exc)
    runtime = StubInMyRndRuntimeClient()
    _patch(monkeypatch, authority, runtime)

    response = client.post('/api/rnd/run', json=VALID_PAYLOAD)
    assert response.status_code == 400, response.text
    assert authority.record_calls == []
    assert runtime.run_calls == []


def test_rnd_run_run_experiment_failure_flagged_ambiguous_never_records(monkeypatch: pytest.MonkeyPatch) -> None:
    exc = RndExecutionError('response truncated', status_code=502, code='RND_EXECUTION_ERROR', execution_may_have_run=True)
    authority = StubRndAuthorityClient()
    runtime = StubInMyRndRuntimeClient(fail_at='run', fail_exc=exc)
    _patch(monkeypatch, authority, runtime)

    response = client.post('/api/rnd/run', json=VALID_PAYLOAD)
    assert response.status_code == 502, response.text
    assert 'already been recorded' in response.text
    assert authority.record_calls == []


def test_rnd_run_clean_run_failure_is_not_flagged_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    exc = RndExecutionError('experiment retention limit reached', status_code=409, code='RND_RETENTION_LIMIT', execution_may_have_run=False)
    authority = StubRndAuthorityClient()
    runtime = StubInMyRndRuntimeClient(fail_at='run', fail_exc=exc)
    _patch(monkeypatch, authority, runtime)

    response = client.post('/api/rnd/run', json=VALID_PAYLOAD)
    assert response.status_code == 409, response.text
    assert 'already been recorded' not in response.text
    assert authority.record_calls == []


def test_rnd_run_digest_mismatch_from_inmyrnd_is_a_fail_closed_502(monkeypatch: pytest.MonkeyPatch) -> None:
    # Structurally unreachable in practice today (InMyR&D has no
    # experiment-edit endpoint), but the defensive check must still work:
    # if InMyR&D's own returned experimentDigest ever disagrees with the
    # one this request authorized, refuse to record rather than trust it.
    authority = StubRndAuthorityClient()
    experiment = _experiment()
    bad_run = _run(experiment, experimentDigest='sha256:' + ('0' * 64))
    runtime = StubInMyRndRuntimeClient(experiments=[experiment], run=bad_run)
    _patch(monkeypatch, authority, runtime)

    response = client.post('/api/rnd/run', json=VALID_PAYLOAD)
    assert response.status_code == 502, response.text
    assert 'different experimentDigest' in response.text
    assert authority.record_calls == []


def test_rnd_run_hub_record_failure_after_a_real_run_is_a_distinct_502(monkeypatch: pytest.MonkeyPatch) -> None:
    exc = RndExecutionError('receipt store full', status_code=503, code='R1_RND_EXECUTION_RECEIPT_STORE_FULL', execution_may_have_run=False)
    authority = StubRndAuthorityClient(fail_at='record', fail_exc=exc)
    runtime = StubInMyRndRuntimeClient()
    _patch(monkeypatch, authority, runtime)

    response = client.post('/api/rnd/run', json=VALID_PAYLOAD)
    assert response.status_code == 502, response.text
    detail = response.json()['detail']
    assert 'InMyR&D experiment run finished' in detail
    assert 'InMyHub' in detail
    assert runtime.run_calls == [EXPERIMENT_ID]


def test_rnd_run_requires_a_project_id(monkeypatch: pytest.MonkeyPatch) -> None:
    authority = StubRndAuthorityClient()
    runtime = StubInMyRndRuntimeClient()
    _patch(monkeypatch, authority, runtime)

    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != 'project_id'}
    response = client.post('/api/rnd/run', json=payload)
    assert response.status_code == 422, response.text
    assert authority.authorize_calls == []


def test_rnd_run_rejects_a_malformed_project_id(monkeypatch: pytest.MonkeyPatch) -> None:
    authority = StubRndAuthorityClient()
    runtime = StubInMyRndRuntimeClient()
    _patch(monkeypatch, authority, runtime)

    payload = dict(VALID_PAYLOAD, project_id='not-a-real-project-id')
    response = client.post('/api/rnd/run', json=payload)
    assert response.status_code == 422, response.text
    assert authority.authorize_calls == []


def test_rnd_run_rejects_an_experiment_id_wearing_a_project_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    authority = StubRndAuthorityClient()
    runtime = StubInMyRndRuntimeClient()
    _patch(monkeypatch, authority, runtime)

    payload = dict(VALID_PAYLOAD, experiment_id=PROJECT_ID)
    response = client.post('/api/rnd/run', json=payload)
    assert response.status_code == 422, response.text
    assert authority.authorize_calls == []


def test_rnd_run_requires_an_idempotency_key(monkeypatch: pytest.MonkeyPatch) -> None:
    authority = StubRndAuthorityClient()
    runtime = StubInMyRndRuntimeClient()
    _patch(monkeypatch, authority, runtime)

    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != 'idempotency_key'}
    response = client.post('/api/rnd/run', json=payload)
    assert response.status_code == 422, response.text
    assert authority.authorize_calls == []


def test_rnd_run_source_never_hardcodes_a_provider_secret() -> None:
    from pathlib import Path
    source = Path('services/api/app/main.py').read_text(encoding='utf-8')
    lowered = source.lower()
    for leak_pattern in ('openrouter.ai', 'api.openai.com', 'openrouter_api_key'):
        assert leak_pattern not in lowered
