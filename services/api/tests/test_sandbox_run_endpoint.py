from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from services.api.app import main
from services.api.app.connect_inmysandbox import SandboxExecutionError, sha256_digest


client = TestClient(main.app)

AUTH_ID = 'sbxauth_' + ('a' * 20)
SANDBOX_ID = 'sbx_' + ('b' * 20)

VALID_PAYLOAD = {
    'command': ['python3', '-c', 'print(1 + 1)'],
    'idempotency_key': 'sandbox-run-endpoint-test-0001',
}

RECEIPT_FIELDS = {
    'schemaVersion', 'receiptId', 'authorizationId', 'providerId', 'actionId',
    'policyDigest', 'commandDigest', 'mode', 'riskClass', 'inputDigest',
    'idempotencyKey', 'executedAt', 'outcome', 'outputs',
}


def _job(**overrides: Any) -> dict[str, Any]:
    base = {
        'id': 'job_test', 'sandboxId': SANDBOX_ID, 'status': 'completed',
        'stdout': 'hi\n', 'stderr': '', 'exitCode': 0, 'timedOut': False,
        'durationMs': 42, 'artifacts': [], 'finishedAt': '2026-08-26T00:00:05Z',
    }
    base.update(overrides)
    return base


class StubSandboxAuthorityClient:
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
        return {'authorizationId': self.authorization_id, 'expiresAt': '2026-08-26T00:06:00Z'}

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
            'receiptId': 'sbxhubr_test',
            'authorizationId': self.authorization_id,
            'outcome': kwargs['executor_receipt']['outcome'],
        }


class StubInMySandboxRuntimeClient:
    def __init__(
        self, *, sandbox_id: str = SANDBOX_ID, job: dict[str, Any] | None = None,
        fail_at: str | None = None, fail_exc: Exception | None = None, destroy_should_fail: bool = False,
    ) -> None:
        self.sandbox_id = sandbox_id
        self.job = job if job is not None else _job()
        self.fail_at = fail_at
        self.fail_exc = fail_exc
        self.destroy_should_fail = destroy_should_fail
        self.create_calls: list[dict[str, Any]] = []
        self.run_calls: list[dict[str, Any]] = []
        self.destroy_calls: list[str] = []

    async def create_sandbox(self, policy: dict[str, Any]) -> dict[str, Any]:
        self.create_calls.append(policy)
        if self.fail_at == 'create':
            raise self.fail_exc
        return {'id': self.sandbox_id, 'status': 'READY'}

    async def run(self, **kwargs: Any) -> dict[str, Any]:
        self.run_calls.append(kwargs)
        if self.fail_at == 'run':
            raise self.fail_exc
        return self.job

    async def destroy(self, sandbox_id: str) -> dict[str, Any]:
        self.destroy_calls.append(sandbox_id)
        if self.destroy_should_fail:
            raise SandboxExecutionError('destroy failed', status_code=503, code='X', execution_may_have_run=False)
        return {'id': sandbox_id, 'status': 'DESTROYED'}


def _patch(monkeypatch: pytest.MonkeyPatch, authority: StubSandboxAuthorityClient, runtime: StubInMySandboxRuntimeClient) -> None:
    monkeypatch.setattr(main, '_sandbox_authority_client', lambda: authority)
    monkeypatch.setattr(main, '_inmysandbox_runtime_client', lambda: runtime)


def test_sandbox_run_happy_path_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    authority = StubSandboxAuthorityClient()
    runtime = StubInMySandboxRuntimeClient()
    _patch(monkeypatch, authority, runtime)

    response = client.post('/api/sandbox/run', json=VALID_PAYLOAD)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['outcome'] == 'completed'
    assert body['exitCode'] == 0
    assert body['hubReceiptId'] == 'sbxhubr_test'
    assert body['authorizationId'] == AUTH_ID

    assert len(authority.authorize_calls) == 1
    assert len(authority.intent_calls) == 1
    assert len(authority.record_calls) == 1
    assert authority.intent_calls[0]['authorization_id'] == AUTH_ID
    assert authority.record_calls[0]['authorization_id'] == AUTH_ID
    assert runtime.create_calls and runtime.run_calls
    assert runtime.destroy_calls == [SANDBOX_ID]

    sent_policy = runtime.create_calls[0]
    assert authority.authorize_calls[0]['policy_digest'] == sha256_digest(sent_policy)
    assert authority.authorize_calls[0]['command_digest'] == sha256_digest(VALID_PAYLOAD['command'])

    receipt = authority.record_calls[0]['executor_receipt']
    assert set(receipt.keys()) == RECEIPT_FIELDS
    assert receipt['mode'] == 'sandbox-execution'
    assert receipt['riskClass'] == 'R1'
    assert receipt['outcome'] == 'completed'
    assert receipt['policyDigest'] == authority.authorize_calls[0]['policy_digest']
    assert receipt['idempotencyKey'] == VALID_PAYLOAD['idempotency_key']


def test_sandbox_run_timed_out_outcome_is_recorded_not_errored(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = StubInMySandboxRuntimeClient(job=_job(timedOut=True, exitCode=None, finishedAt=None))
    authority = StubSandboxAuthorityClient()
    _patch(monkeypatch, authority, runtime)

    response = client.post('/api/sandbox/run', json=VALID_PAYLOAD)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['outcome'] == 'timed_out'
    assert authority.record_calls[0]['executor_receipt']['outcome'] == 'timed_out'


def test_sandbox_run_nonzero_exit_is_a_failed_outcome_not_an_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = StubInMySandboxRuntimeClient(job=_job(exitCode=1, stderr='boom'))
    authority = StubSandboxAuthorityClient()
    _patch(monkeypatch, authority, runtime)

    response = client.post('/api/sandbox/run', json=VALID_PAYLOAD)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['outcome'] == 'failed'
    assert body['exitCode'] == 1
    assert authority.record_calls[0]['executor_receipt']['outcome'] == 'failed'


def test_sandbox_run_authorize_failure_stops_before_any_side_effect(monkeypatch: pytest.MonkeyPatch) -> None:
    exc = SandboxExecutionError('Hub unavailable', status_code=503, code='R1_SANDBOX_AUTHORITY_UNAVAILABLE', execution_may_have_run=False)
    authority = StubSandboxAuthorityClient(fail_at='authorize', fail_exc=exc)
    runtime = StubInMySandboxRuntimeClient()
    _patch(monkeypatch, authority, runtime)

    response = client.post('/api/sandbox/run', json=VALID_PAYLOAD)
    assert response.status_code == 503, response.text
    assert 'Hub unavailable' in response.text
    assert 'may have already started' not in response.text
    assert authority.intent_calls == []
    assert authority.record_calls == []
    assert runtime.create_calls == []
    assert runtime.run_calls == []
    assert runtime.destroy_calls == []


def test_sandbox_run_intent_failure_stops_before_runtime_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    exc = SandboxExecutionError('bad intent', status_code=400, code='R1_SANDBOX_EXECUTION_INTENT_INVALID', execution_may_have_run=False)
    authority = StubSandboxAuthorityClient(fail_at='intent', fail_exc=exc)
    runtime = StubInMySandboxRuntimeClient()
    _patch(monkeypatch, authority, runtime)

    response = client.post('/api/sandbox/run', json=VALID_PAYLOAD)
    assert response.status_code == 400, response.text
    assert authority.record_calls == []
    assert runtime.create_calls == []
    assert runtime.destroy_calls == []


def test_sandbox_run_create_failure_is_clean_not_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    exc = SandboxExecutionError('too many active sandboxes', status_code=429, code='SANDBOX_LIMIT_EXCEEDED', execution_may_have_run=False)
    authority = StubSandboxAuthorityClient()
    runtime = StubInMySandboxRuntimeClient(fail_at='create', fail_exc=exc)
    _patch(monkeypatch, authority, runtime)

    response = client.post('/api/sandbox/run', json=VALID_PAYLOAD)
    assert response.status_code == 429, response.text
    assert 'may have already started' not in response.text
    # No sandbox id was ever obtained, so there is nothing to destroy.
    assert runtime.destroy_calls == []
    assert authority.record_calls == []


def test_sandbox_run_run_failure_flagged_ambiguous_still_destroys_and_never_records(monkeypatch: pytest.MonkeyPatch) -> None:
    exc = SandboxExecutionError('response truncated', status_code=502, code='SANDBOX_EXECUTION_ERROR', execution_may_have_run=True)
    authority = StubSandboxAuthorityClient()
    runtime = StubInMySandboxRuntimeClient(fail_at='run', fail_exc=exc)
    _patch(monkeypatch, authority, runtime)

    response = client.post('/api/sandbox/run', json=VALID_PAYLOAD)
    assert response.status_code == 502, response.text
    assert 'may have already started' in response.text
    # create_sandbox succeeded, so best-effort destroy must still run.
    assert runtime.destroy_calls == [SANDBOX_ID]
    assert authority.record_calls == []


def test_sandbox_run_destroy_failure_does_not_mask_a_successful_result(monkeypatch: pytest.MonkeyPatch) -> None:
    authority = StubSandboxAuthorityClient()
    runtime = StubInMySandboxRuntimeClient(destroy_should_fail=True)
    _patch(monkeypatch, authority, runtime)

    response = client.post('/api/sandbox/run', json=VALID_PAYLOAD)
    assert response.status_code == 200, response.text
    assert response.json()['outcome'] == 'completed'
    assert runtime.destroy_calls == [SANDBOX_ID]


def test_sandbox_run_hub_record_failure_after_a_real_run_is_a_distinct_502(monkeypatch: pytest.MonkeyPatch) -> None:
    exc = SandboxExecutionError('receipt store full', status_code=503, code='R1_SANDBOX_EXECUTION_RECEIPT_STORE_FULL', execution_may_have_run=False)
    authority = StubSandboxAuthorityClient(fail_at='record', fail_exc=exc)
    runtime = StubInMySandboxRuntimeClient()
    _patch(monkeypatch, authority, runtime)

    response = client.post('/api/sandbox/run', json=VALID_PAYLOAD)
    assert response.status_code == 502, response.text
    detail = response.json()['detail']
    assert 'outcome=completed' in detail
    assert 'InMyHub' in detail
    # The sandbox really did run and was cleaned up before the Hub call failed.
    assert runtime.destroy_calls == [SANDBOX_ID]
    assert runtime.run_calls


def test_sandbox_run_rejects_inputs_over_the_combined_128kib_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    authority = StubSandboxAuthorityClient()
    runtime = StubInMySandboxRuntimeClient()
    _patch(monkeypatch, authority, runtime)

    payload = dict(VALID_PAYLOAD, inputs=[{'path': 'big.txt', 'content': 'x' * 131_073}])
    response = client.post('/api/sandbox/run', json=payload)
    assert response.status_code == 422, response.text
    # Pydantic validation must reject this before the handler runs at all.
    assert authority.authorize_calls == []
    assert runtime.create_calls == []


def test_sandbox_run_rejects_a_subdirectory_input_path(monkeypatch: pytest.MonkeyPatch) -> None:
    authority = StubSandboxAuthorityClient()
    runtime = StubInMySandboxRuntimeClient()
    _patch(monkeypatch, authority, runtime)

    payload = dict(VALID_PAYLOAD, inputs=[{'path': 'sub/dir.txt', 'content': 'x'}])
    response = client.post('/api/sandbox/run', json=payload)
    assert response.status_code == 422, response.text
    assert authority.authorize_calls == []


def test_sandbox_run_requires_a_command(monkeypatch: pytest.MonkeyPatch) -> None:
    authority = StubSandboxAuthorityClient()
    runtime = StubInMySandboxRuntimeClient()
    _patch(monkeypatch, authority, runtime)

    response = client.post('/api/sandbox/run', json={'command': [], 'idempotency_key': 'sandbox-run-empty-cmd-0001'})
    assert response.status_code == 422, response.text
    assert authority.authorize_calls == []


def test_sandbox_run_requires_an_idempotency_key(monkeypatch: pytest.MonkeyPatch) -> None:
    authority = StubSandboxAuthorityClient()
    runtime = StubInMySandboxRuntimeClient()
    _patch(monkeypatch, authority, runtime)

    response = client.post('/api/sandbox/run', json={'command': ['echo', 'hi']})
    assert response.status_code == 422, response.text
    assert authority.authorize_calls == []


def test_sandbox_run_source_never_hardcodes_a_provider_secret() -> None:
    from pathlib import Path
    source = Path('services/api/app/main.py').read_text(encoding='utf-8')
    lowered = source.lower()
    for leak_pattern in ('openrouter.ai', 'api.openai.com', 'openrouter_api_key'):
        assert leak_pattern not in lowered
